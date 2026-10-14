package ephemeral

import (
	"context"
	"encoding/base64"
	"fmt"
	"log/slog"

	"github.com/google/uuid"
)

const (
	defaultClusterDuration        = "4h"
	defaultClusterPool            = "rosa-default"
	kubeconfigSecretSuffix        = "-kubeconfig"
	kubeconfigSecretNamespace     = "ephemeral-cluster-operator"
)

// ClusterReservationResult holds the result of a cluster reservation operation.
type ClusterReservationResult struct {
	Name        string
	Type        string
	State       string
	ClusterName string
	ConsoleURL  string
	Expiration  string
	Requester   string
	Pool        string
	Duration    string
	Created     string
}

// ClusterReserveOptions holds optional parameters for ReserveCluster.
type ClusterReserveOptions struct {
	// Name is the reservation name. Auto-generated if empty.
	Name string
	// Duration is the reservation duration. Defaults to "4h".
	Duration string
	// Requester is the requester identity. Defaults to client.Whoami().
	Requester string
	// Pool is the cluster pool. Defaults to "rosa-default".
	Pool string
	// Team is an optional team name for cost attribution.
	Team string
}

// ReserveCluster creates a ClusterReservation CR and returns immediately.
// Unlike namespace reservations, cluster provisioning is async (20–40 min).
// The caller must poll GetClusterStatus() until state is "active".
// Mirrors bonfire_lib/clusters.py:reserve_cluster().
func ReserveCluster(ctx context.Context, client Client, opts ClusterReserveOptions) (*ClusterReservationResult, error) {
	if opts.Name == "" {
		id := uuid.New().String()
		opts.Name = "cluster-reservation-" + id[:8]
	}
	if opts.Duration == "" {
		opts.Duration = defaultClusterDuration
	}
	if opts.Pool == "" {
		opts.Pool = defaultClusterPool
	}
	if opts.Requester == "" {
		opts.Requester = client.Whoami(ctx)
		if opts.Requester == "" {
			opts.Requester = "bonfire"
		}
	}

	existing, err := client.GetClusterReservation(ctx, opts.Name)
	if err != nil {
		return nil, fmt.Errorf("checking for existing cluster reservation: %w", err)
	}
	if existing != nil {
		return nil, NewFatalError("Cluster reservation with name %s already exists", opts.Name)
	}

	body := renderClusterReservation(opts.Name, opts.Duration, opts.Requester, opts.Pool, opts.Team)
	if _, err = client.CreateClusterReservation(ctx, body); err != nil {
		return nil, fmt.Errorf("create cluster reservation: %w", err)
	}

	slog.Info("cluster reservation created",
		"name", opts.Name,
		"requester", opts.Requester,
		"duration", opts.Duration,
		"pool", opts.Pool,
	)

	return &ClusterReservationResult{
		Name:      opts.Name,
		State:     "waiting",
		Requester: opts.Requester,
		Pool:      opts.Pool,
		Type:      "cluster",
	}, nil
}

// ReleaseCluster releases a cluster reservation by setting spec.duration to "0s".
// Mirrors bonfire_lib/clusters.py:release_cluster().
func ReleaseCluster(ctx context.Context, client Client, name string) (*ReleaseResult, error) {
	res, err := client.GetClusterReservation(ctx, name)
	if err != nil {
		return nil, err
	}
	if res == nil {
		return nil, NewFatalError("Cluster reservation %q not found", name)
	}

	if _, err = client.PatchClusterReservation(ctx, name, map[string]any{
		"spec": map[string]any{"duration": "0s"},
	}); err != nil {
		return nil, fmt.Errorf("patch cluster reservation %q: %w", name, err)
	}

	slog.Info("releasing cluster reservation", "name", name)
	return &ReleaseResult{Name: name, Released: true}, nil
}

// ExtendCluster adds the given duration to a cluster reservation's current duration.
// Mirrors bonfire_lib/clusters.py:extend_cluster().
func ExtendCluster(ctx context.Context, client Client, name, duration string) (*ExtendResult, error) {
	res, err := client.GetClusterReservation(ctx, name)
	if err != nil {
		return nil, err
	}
	if res == nil {
		return nil, NewFatalError("Cluster reservation %q not found", name)
	}

	state := nestedString(res, "status", "state")
	if state == "expired" {
		return nil, NewFatalError("Cluster reservation %q has expired. Reserve a new cluster.", name)
	}

	prevSecs, err := HMSToSeconds(nestedString(res, "spec", "duration"))
	if err != nil {
		return nil, fmt.Errorf("invalid existing duration: %w", err)
	}
	addSecs, err := HMSToSeconds(duration)
	if err != nil {
		return nil, fmt.Errorf("invalid extend duration: %w", err)
	}
	newDuration := DurationFmt(prevSecs + addSecs)

	if _, err = client.PatchClusterReservation(ctx, name, map[string]any{
		"spec": map[string]any{"duration": newDuration},
	}); err != nil {
		return nil, fmt.Errorf("patch cluster reservation %q: %w", name, err)
	}

	slog.Info("cluster reservation extended", "name", name, "added", duration, "newTotal", newDuration)
	return &ExtendResult{Name: name, NewDuration: newDuration}, nil
}

// GetClusterStatus returns the status of a cluster reservation.
// Returns nil, nil if not found.
// Mirrors bonfire_lib/clusters.py:get_cluster_status().
func GetClusterStatus(ctx context.Context, client Client, name string) (*ClusterReservationResult, error) {
	res, err := client.GetClusterReservation(ctx, name)
	if err != nil {
		return nil, err
	}
	if res == nil {
		return nil, nil
	}
	return clusterReservationResult(res), nil
}

// GetKubeconfig fetches kubeconfig YAML for a provisioned cluster reservation.
// The cluster must be in "active" state.
// Mirrors bonfire_lib/clusters.py:get_kubeconfig().
func GetKubeconfig(ctx context.Context, client Client, name string) (string, error) {
	res, err := client.GetClusterReservation(ctx, name)
	if err != nil {
		return "", err
	}
	if res == nil {
		return "", NewFatalError("Cluster reservation %q not found", name)
	}

	clusterName := nestedString(res, "status", "clusterName")
	if clusterName == "" {
		state := nestedString(res, "status", "state")
		return "", NewFatalError(
			"Cluster not yet assigned to reservation %q (state: %s). Poll with GetClusterStatus() until state is 'active'.",
			name, state,
		)
	}

	secretName := clusterName + kubeconfigSecretSuffix
	secret, err := client.GetSecret(ctx, secretName, kubeconfigSecretNamespace)
	if err != nil {
		return "", err
	}
	if secret == nil {
		return "", NewFatalError(
			"Kubeconfig Secret %q not found in namespace %q. The cluster may still be bootstrapping.",
			secretName, kubeconfigSecretNamespace,
		)
	}

	// Try "kubeconfig" key first, then "value"
	raw, ok := secret.Data["kubeconfig"]
	if !ok || len(raw) == 0 {
		raw = secret.Data["value"]
	}
	if len(raw) == 0 {
		return "", NewFatalError("Kubeconfig Secret %q exists but contains no kubeconfig data.", secretName)
	}

	// The API server already base64-decodes secret data, so raw is the actual bytes.
	// Attempt a second base64 decode to match the Python implementation's behaviour.
	decoded, err2 := base64.StdEncoding.DecodeString(string(raw))
	if err2 != nil {
		return string(raw), nil
	}
	return string(decoded), nil
}

// ListClusterReservations lists cluster reservations, optionally filtered by requester.
// Returns empty slice if the ClusterReservation CRD is not installed.
// Mirrors bonfire_lib/clusters.py:list_cluster_reservations().
func ListClusterReservations(ctx context.Context, client Client, requester string) ([]ClusterReservationResult, error) {
	var selector string
	if requester != "" {
		selector = "requester=" + requester
	}
	raw, err := client.ListClusterReservations(ctx, selector)
	if err != nil {
		slog.Debug("ClusterReservation CRD not available")
		return []ClusterReservationResult{}, nil
	}
	out := make([]ClusterReservationResult, 0, len(raw))
	for _, res := range raw {
		out = append(out, *clusterReservationResult(res))
	}
	return out, nil
}

func clusterReservationResult(res map[string]any) *ClusterReservationResult {
	return &ClusterReservationResult{
		Name:        nestedString(res, "metadata", "name"),
		Type:        "cluster",
		State:       nestedString(res, "status", "state"),
		ClusterName: nestedString(res, "status", "clusterName"),
		ConsoleURL:  nestedString(res, "status", "consoleURL"),
		Expiration:  nestedString(res, "status", "expiration"),
		Requester:   nestedString(res, "spec", "requester"),
		Pool:        nestedString(res, "spec", "pool"),
		Duration:    nestedString(res, "spec", "duration"),
		Created:     nestedString(res, "metadata", "creationTimestamp"),
	}
}

// renderClusterReservation builds the ClusterReservation CR body as a map.
// Replaces the Jinja2 clusterreservation.yaml.j2 template.
func renderClusterReservation(name, duration, requester, pool, team string) map[string]any {
	spec := map[string]any{
		"duration":  duration,
		"requester": requester,
		"pool":      pool,
	}
	if team != "" {
		spec["team"] = team
	}
	return map[string]any{
		"apiVersion": "cloud.redhat.com/v1alpha1",
		"kind":       "ClusterReservation",
		"metadata": map[string]any{
			"name": name,
			"labels": map[string]any{
				"requester": requester,
			},
		},
		"spec": spec,
	}
}
