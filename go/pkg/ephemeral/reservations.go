package ephemeral

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/google/uuid"
)

const defaultReservationTimeout = 600 // 10 minutes

// ReservationResult holds the result of a successful namespace reservation.
type ReservationResult struct {
	Name       string
	Namespace  string
	State      string
	Expiration string
	Requester  string
	Pool       string
}

// ReserveOptions holds optional parameters for Reserve.
type ReserveOptions struct {
	// Name is the reservation name. Auto-generated if empty.
	Name string
	// Duration is the reservation duration (e.g. "1h"). Defaults to "1h".
	Duration string
	// Requester is the requester identity. Defaults to client.Whoami().
	Requester string
	// Pool is the namespace pool to reserve from. Defaults to "default".
	Pool string
	// Team is an optional team name for cost attribution.
	Team string
	// SecretsSourceNamespace overrides the secret source namespace.
	SecretsSourceNamespace string
	// Timeout is max seconds to wait for namespace assignment. Defaults to 600.
	Timeout int
}

// Reserve creates a NamespaceReservation CR and polls until a namespace is assigned.
// Mirrors bonfire_lib/reservations.py:reserve().
//
// Returns ReservationResult on success.
// Returns *FatalError if reservation already exists.
// Returns context.DeadlineExceeded or a timeout error if namespace not assigned within Timeout.
func Reserve(ctx context.Context, client Client, opts ReserveOptions) (*ReservationResult, error) {
	if opts.Name == "" {
		id := uuid.New().String()
		opts.Name = "bonfire-reservation-" + id[:8]
	}
	if opts.Duration == "" {
		opts.Duration = "1h"
	}
	if opts.Pool == "" {
		opts.Pool = "default"
	}
	if opts.Timeout == 0 {
		opts.Timeout = defaultReservationTimeout
	}
	if opts.Requester == "" {
		opts.Requester = client.Whoami(ctx)
		if opts.Requester == "" {
			opts.Requester = "bonfire"
		}
	}

	existing, err := client.GetReservation(ctx, opts.Name)
	if err != nil {
		return nil, fmt.Errorf("checking for existing reservation: %w", err)
	}
	if existing != nil {
		return nil, NewFatalError("Reservation with name %s already exists", opts.Name)
	}

	body := renderReservation(opts.Name, opts.Duration, opts.Requester, opts.Pool, opts.Team, opts.SecretsSourceNamespace)
	if _, err = client.CreateReservation(ctx, body); err != nil {
		return nil, fmt.Errorf("create reservation: %w", err)
	}

	nsName, err := WaitOnReservation(ctx, client, opts.Name, opts.Timeout)
	if err != nil {
		// Auto-release the pending CR on timeout, matching Python behaviour.
		slog.Info("timeout waiting for namespace, cancelling reservation", "name", opts.Name)
		_, _ = Release(ctx, client, ReleaseOptions{Name: opts.Name})
		return nil, err
	}

	res, err := client.GetReservation(ctx, opts.Name)
	if err != nil {
		return nil, err
	}

	slog.Info("namespace reserved",
		"namespace", nsName,
		"requester", opts.Requester,
		"duration", opts.Duration,
		"pool", opts.Pool,
	)

	return &ReservationResult{
		Name:       opts.Name,
		Namespace:  nsName,
		State:      nestedString(res, "status", "state"),
		Expiration: nestedString(res, "status", "expiration"),
		Requester:  opts.Requester,
		Pool:       opts.Pool,
	}, nil
}

// ReleaseOptions holds parameters for Release.
type ReleaseOptions struct {
	// Name is the reservation name (mutually exclusive with Namespace).
	Name string
	// Namespace is the namespace name to find the reservation for.
	Namespace string
}

// ReleaseResult holds the result of a release operation.
type ReleaseResult struct {
	Name     string
	Released bool
}

// Release releases a reservation by setting spec.duration to "0s".
// The ENO operator detects this within ~10 seconds and cascades deletion via OwnerRef.
// Mirrors bonfire_lib/reservations.py:release().
func Release(ctx context.Context, client Client, opts ReleaseOptions) (*ReleaseResult, error) {
	res, err := findReservation(ctx, client, opts.Name, opts.Namespace)
	if err != nil {
		return nil, err
	}

	resName := nestedString(res, "metadata", "name")
	if _, err = client.PatchReservation(ctx, resName, map[string]any{
		"spec": map[string]any{"duration": "0s"},
	}); err != nil {
		return nil, fmt.Errorf("patch reservation %q: %w", resName, err)
	}

	slog.Info("releasing reservation", "name", resName)
	return &ReleaseResult{Name: resName, Released: true}, nil
}

// ExtendResult holds the result of an extend operation.
type ExtendResult struct {
	Name        string
	NewDuration string
}

// Extend adds the given duration to a reservation's current duration.
// Namespace is used to look up the reservation.
// Mirrors bonfire_lib/reservations.py:extend().
func Extend(ctx context.Context, client Client, namespace, duration string) (*ExtendResult, error) {
	res, err := findReservation(ctx, client, "", namespace)
	if err != nil {
		return nil, err
	}

	state := nestedString(res, "status", "state")
	if state == "expired" {
		return nil, NewFatalError("Reservation for namespace %s has expired. Reserve a new namespace.", namespace)
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

	resName := nestedString(res, "metadata", "name")
	if _, err = client.PatchReservation(ctx, resName, map[string]any{
		"spec": map[string]any{"duration": newDuration},
	}); err != nil {
		return nil, fmt.Errorf("patch reservation %q: %w", resName, err)
	}

	slog.Info("reservation extended",
		"namespace", namespace,
		"added", duration,
		"newTotal", newDuration,
	)
	return &ExtendResult{Name: resName, NewDuration: newDuration}, nil
}

// findReservation finds a reservation by name or namespace.
// Exactly one of name/namespace must be non-empty.
func findReservation(ctx context.Context, client Client, name, namespace string) (map[string]any, error) {
	switch {
	case name != "":
		res, err := client.GetReservation(ctx, name)
		if err != nil {
			return nil, err
		}
		if res == nil {
			return nil, NewFatalError("Reservation %q not found", name)
		}
		return res, nil

	case namespace != "":
		all, err := client.ListReservations(ctx, "")
		if err != nil {
			return nil, err
		}
		for _, res := range all {
			if nestedString(res, "status", "namespace") == namespace {
				return res, nil
			}
		}
		return nil, NewFatalError("No reservation found for namespace %q", namespace)

	default:
		return nil, NewFatalError("Must provide either name or namespace")
	}
}

// renderReservation builds the NamespaceReservation CR body as a map.
// Replaces the Jinja2 reservation.yaml.j2 template.
func renderReservation(name, duration, requester, pool, team, secretsSourceNamespace string) map[string]any {
	spec := map[string]any{
		"duration":  duration,
		"requester": requester,
		"pool":      pool,
	}
	if team != "" {
		spec["team"] = team
	}
	if secretsSourceNamespace != "" {
		spec["secretSourceNamespace"] = secretsSourceNamespace
	}

	return map[string]any{
		"apiVersion": "cloud.redhat.com/v1alpha1",
		"kind":       "NamespaceReservation",
		"metadata": map[string]any{
			"name": name,
			"labels": map[string]any{
				"requester": requester,
			},
		},
		"spec": spec,
	}
}
