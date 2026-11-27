package ephemeral

import (
	"context"
	"encoding/base64"
	"fmt"
	"log/slog"
	"time"
)

// ReservationSummary is a flattened view of a NamespaceReservation CR.
type ReservationSummary struct {
	Name       string
	Namespace  string
	State      string
	Expiration string
	Requester  string
	Pool       string
	Duration   string
}

// GetReservation looks up a reservation by name, namespace, or requester.
// At most one parameter should be non-empty; returns nil, nil if not found.
// Mirrors bonfire_lib/status.py:get_reservation().
func GetReservation(ctx context.Context, client Client, name, namespace, requester string) (map[string]any, error) {
	switch {
	case name != "":
		return client.GetReservation(ctx, name)

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
		return nil, nil

	case requester != "":
		all, err := client.ListReservations(ctx, "requester="+requester)
		if err != nil {
			return nil, err
		}
		if len(all) == 1 {
			return all[0], nil
		}
		if len(all) > 1 {
			slog.Info("multiple reservations found for requester", "requester", requester)
		}
		return nil, nil

	default:
		return nil, nil
	}
}

// GetReservationSummary extracts a structured summary from a raw reservation dict.
func GetReservationSummary(res map[string]any) ReservationSummary {
	return ReservationSummary{
		Name:       nestedString(res, "metadata", "name"),
		Namespace:  nestedString(res, "status", "namespace"),
		State:      nestedString(res, "status", "state"),
		Expiration: nestedString(res, "status", "expiration"),
		Requester:  nestedString(res, "spec", "requester"),
		Pool:       nestedString(res, "spec", "pool"),
		Duration:   nestedString(res, "spec", "duration"),
	}
}

// ListReservations lists all reservations, optionally filtered by requester.
// Mirrors bonfire_lib/status.py:list_reservations().
func ListReservations(ctx context.Context, client Client, requester string) ([]ReservationSummary, error) {
	var selector string
	if requester != "" {
		selector = "requester=" + requester
	}
	all, err := client.ListReservations(ctx, selector)
	if err != nil {
		return nil, err
	}
	out := make([]ReservationSummary, len(all))
	for i, res := range all {
		out[i] = GetReservationSummary(res)
	}
	return out, nil
}

// WaitOnReservation polls a reservation until status.namespace is populated.
// Returns the assigned namespace name.
// Returns an error if timeout is exceeded (caller should release the reservation).
// Mirrors bonfire_lib/status.py:wait_on_reservation().
func WaitOnReservation(ctx context.Context, client Client, name string, timeoutSecs int) (string, error) {
	slog.Info("waiting for reservation to be picked up by operator", "name", name)
	deadline := time.Now().Add(time.Duration(timeoutSecs) * time.Second)
	for time.Now().Before(deadline) {
		res, err := client.GetReservation(ctx, name)
		if err != nil {
			return "", err
		}
		if res != nil {
			if ns := nestedString(res, "status", "namespace"); ns != "" {
				return ns, nil
			}
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
	return "", fmt.Errorf("timed out after %ds waiting for namespace on reservation %q", timeoutSecs, name)
}

// CheckForExistingReservation returns true if the requester already has an active reservation
// with a live namespace.
// Mirrors bonfire_lib/status.py:check_for_existing_reservation().
func CheckForExistingReservation(ctx context.Context, client Client, requester string) (bool, error) {
	all, err := client.ListReservations(ctx, "")
	if err != nil {
		return false, err
	}
	for _, res := range all {
		if nestedString(res, "spec", "requester") == requester &&
			nestedString(res, "status", "state") == "active" {
			ns := nestedString(res, "status", "namespace")
			if ns == "" {
				continue
			}
			nsObj, err := client.GetNamespace(ctx, ns)
			if err != nil {
				return false, err
			}
			if nsObj != nil {
				return true, nil
			}
		}
	}
	return false, nil
}

// GetConsoleURL returns the OpenShift console URL from the cluster's console-public ConfigMap.
// Returns "" if not available.
// Mirrors bonfire_lib/status.py:get_console_url().
func GetConsoleURL(ctx context.Context, client Client) string {
	cm, err := client.GetConfigMap(ctx, "console-public", "openshift-config-managed")
	if err != nil {
		slog.Debug("unable to obtain console url", "err", err)
		return ""
	}
	if cm == nil {
		return ""
	}
	return cm.Data["consoleURL"]
}

// NamespaceDescription holds detailed information about an ephemeral namespace.
type NamespaceDescription struct {
	Namespace              string
	ConsoleNamespaceRoute  string
	KeycloakAdminRoute     string
	KeycloakAdminUsername  string
	KeycloakAdminPassword  string
	ClowdAppsDeployed      int
	FrontendsDeployed      int
	DefaultUsername        string
	DefaultPassword        string
	GatewayRoute           string
	HasCluster             bool
}

// DescribeNamespace returns detailed information about an ephemeral namespace.
// Mirrors bonfire_lib/status.py:describe_namespace().
func DescribeNamespace(ctx context.Context, client Client, namespace string) (*NamespaceDescription, error) {
	ns, err := client.GetNamespace(ctx, namespace)
	if err != nil {
		return nil, fmt.Errorf("get namespace: %w", err)
	}
	if ns == nil {
		return nil, NewFatalError("namespace %q not found", namespace)
	}
	if ns.Labels["operator-ns"] != "true" {
		return nil, NewFatalError("namespace %q was not reserved with namespace operator", namespace)
	}

	clowdApps, err := client.ListCRDs(ctx, gvrClowdApp, namespace)
	if err != nil {
		slog.Warn("failed to list ClowdApps", "namespace", namespace, "err", err)
		clowdApps = nil
	}

	frontends, err := client.ListCRDs(ctx, gvrFrontend, namespace)
	if err != nil {
		slog.Warn("failed to list Frontends", "namespace", namespace, "err", err)
		frontends = nil
	}

	var feHost, keycloakURL string
	feEnv, err := client.GetCRD(ctx, gvrFrontendEnvironment, "env-"+namespace, "")
	if err != nil {
		slog.Warn("failed to get FrontendEnvironment", "namespace", namespace, "err", err)
	} else if feEnv != nil {
		feHost = nestedString(feEnv, "spec", "hostname")
		keycloakURL = nestedString(feEnv, "spec", "sso")
	}

	kc := getKeycloakCreds(ctx, client, namespace)
	consoleURL := GetConsoleURL(ctx, client)
	nsURL := ""
	if consoleURL != "" {
		nsURL = consoleURL + "/k8s/cluster/projects/" + namespace
	}

	hasCluster := hasClusterKubeconfig(ctx, client, namespace)

	gwRoute := ""
	if feHost != "" {
		gwRoute = "https://" + feHost
	}

	return &NamespaceDescription{
		Namespace:             namespace,
		ConsoleNamespaceRoute: nsURL,
		KeycloakAdminRoute:    keycloakURL,
		KeycloakAdminUsername: kc["username"],
		KeycloakAdminPassword: kc["password"],
		ClowdAppsDeployed:     len(clowdApps),
		FrontendsDeployed:     len(frontends),
		DefaultUsername:       kc["defaultUsername"],
		DefaultPassword:       kc["defaultPassword"],
		GatewayRoute:          gwRoute,
		HasCluster:            hasCluster,
	}, nil
}

func hasClusterKubeconfig(ctx context.Context, client Client, namespace string) bool {
	secret, err := client.GetSecret(ctx, namespace+"-cluster-kubeconfig", namespace)
	return err == nil && secret != nil
}

func getKeycloakCreds(ctx context.Context, client Client, namespace string) map[string]string {
	result := map[string]string{
		"username":        "N/A",
		"password":        "N/A",
		"defaultUsername": "N/A",
		"defaultPassword": "N/A",
	}
	secret, err := client.GetSecret(ctx, "env-"+namespace+"-keycloak", namespace)
	if err != nil || secret == nil {
		return result
	}
	for _, key := range []string{"username", "password", "defaultUsername", "defaultPassword"} {
		raw, ok := secret.Data[key]
		if !ok || len(raw) == 0 {
			continue
		}
		// Secret data is already []byte (base64-decoded by the API server).
		// But in the Python implementation it is double-decoded, so match that.
		decoded, err := base64.StdEncoding.DecodeString(string(raw))
		if err != nil {
			// Already raw bytes from API server
			result[key] = string(raw)
		} else {
			result[key] = string(decoded)
		}
	}
	return result
}
