package ephemeral

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

func TestGetReservation_ByName(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.getReservationFn = func(_ context.Context, _ string) (map[string]any, error) {
		return res, nil
	}
	got, err := GetReservation(context.Background(), mc, "test-reservation", "", "")
	mustNotErr(t, err)
	if got == nil {
		t.Fatal("expected non-nil result")
	}
	if nestedString(got, "metadata", "name") != "test-reservation" {
		t.Errorf("name = %q, want %q", nestedString(got, "metadata", "name"), "test-reservation")
	}
}

func TestGetReservation_ByNameNotFound(t *testing.T) {
	mc := noopClient()
	mc.getReservationFn = func(_ context.Context, _ string) (map[string]any, error) {
		return nil, nil
	}
	got, err := GetReservation(context.Background(), mc, "nonexistent", "", "")
	mustNotErr(t, err)
	if got != nil {
		t.Errorf("expected nil, got %v", got)
	}
}

func TestGetReservation_ByNamespace(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res}, nil
	}
	got, err := GetReservation(context.Background(), mc, "", "ephemeral-abc123", "")
	mustNotErr(t, err)
	if got == nil {
		t.Fatal("expected non-nil result")
	}
}

func TestGetReservation_ByNamespaceNotFound(t *testing.T) {
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{}, nil
	}
	got, err := GetReservation(context.Background(), mc, "", "nonexistent", "")
	mustNotErr(t, err)
	if got != nil {
		t.Errorf("expected nil, got %v", got)
	}
}

func TestGetReservation_ByRequesterSingle(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res}, nil
	}
	got, err := GetReservation(context.Background(), mc, "", "", "test-user")
	mustNotErr(t, err)
	if got == nil {
		t.Fatal("expected non-nil result for single reservation")
	}
}

func TestGetReservation_ByRequesterMultiple(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res, res}, nil
	}
	got, err := GetReservation(context.Background(), mc, "", "", "test-user")
	mustNotErr(t, err)
	if got != nil {
		t.Error("expected nil for multiple reservations")
	}
}

func TestGetReservation_NoArgs(t *testing.T) {
	mc := noopClient()
	got, err := GetReservation(context.Background(), mc, "", "", "")
	mustNotErr(t, err)
	if got != nil {
		t.Errorf("expected nil, got %v", got)
	}
}

func TestListReservations_All(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res}, nil
	}
	result, err := ListReservations(context.Background(), mc, "")
	mustNotErr(t, err)
	if len(result) != 1 {
		t.Fatalf("len = %d, want 1", len(result))
	}
	s := result[0]
	if s.Name != "test-reservation" {
		t.Errorf("Name = %q, want %q", s.Name, "test-reservation")
	}
	if s.Namespace != "ephemeral-abc123" {
		t.Errorf("Namespace = %q", s.Namespace)
	}
	if s.State != "active" {
		t.Errorf("State = %q", s.State)
	}
	if s.Requester != "test-user" {
		t.Errorf("Requester = %q", s.Requester)
	}
	if s.Pool != "default" {
		t.Errorf("Pool = %q", s.Pool)
	}
	if s.Duration != "1h" {
		t.Errorf("Duration = %q", s.Duration)
	}
}

func TestListReservations_FilteredByRequester(t *testing.T) {
	res := sampleReservation()
	var gotSelector string
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, sel string) ([]map[string]any, error) {
		gotSelector = sel
		return []map[string]any{res}, nil
	}
	_, err := ListReservations(context.Background(), mc, "test-user")
	mustNotErr(t, err)
	if gotSelector != "requester=test-user" {
		t.Errorf("selector = %q, want %q", gotSelector, "requester=test-user")
	}
}

func TestWaitOnReservation_ReturnsWhenNamespaceSet(t *testing.T) {
	calls := 0
	mc := noopClient()
	mc.getReservationFn = func(_ context.Context, _ string) (map[string]any, error) {
		calls++
		if calls == 1 {
			return map[string]any{"status": map[string]any{}}, nil
		}
		return map[string]any{"status": map[string]any{"namespace": "ephemeral-xyz"}}, nil
	}
	ns, err := WaitOnReservation(context.Background(), mc, "test-res", 10)
	mustNotErr(t, err)
	if ns != "ephemeral-xyz" {
		t.Errorf("namespace = %q, want %q", ns, "ephemeral-xyz")
	}
}

func TestWaitOnReservation_Timeout(t *testing.T) {
	mc := noopClient()
	mc.getReservationFn = func(_ context.Context, _ string) (map[string]any, error) {
		// Simulate a sleep so the 1s timeout elapses quickly
		time.Sleep(10 * time.Millisecond)
		return map[string]any{"status": map[string]any{}}, nil
	}
	_, err := WaitOnReservation(context.Background(), mc, "test-res", 0)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if !strings.Contains(err.Error(), "timed out") {
		t.Errorf("error %q should contain 'timed out'", err.Error())
	}
}

func TestCheckForExistingReservation_HasActive(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res}, nil
	}
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "ephemeral-abc123"}}, nil
	}
	ok, err := CheckForExistingReservation(context.Background(), mc, "test-user")
	mustNotErr(t, err)
	if !ok {
		t.Error("expected true")
	}
}

func TestCheckForExistingReservation_NoActive(t *testing.T) {
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{}, nil
	}
	ok, err := CheckForExistingReservation(context.Background(), mc, "test-user")
	mustNotErr(t, err)
	if ok {
		t.Error("expected false")
	}
}

func TestCheckForExistingReservation_ReservationButNsGone(t *testing.T) {
	res := sampleReservation()
	mc := noopClient()
	mc.listReservationsFn = func(_ context.Context, _ string) ([]map[string]any, error) {
		return []map[string]any{res}, nil
	}
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return nil, nil
	}
	ok, err := CheckForExistingReservation(context.Background(), mc, "test-user")
	mustNotErr(t, err)
	if ok {
		t.Error("expected false when namespace is gone")
	}
}

func TestGetConsoleURL_ReturnsURL(t *testing.T) {
	mc := noopClient()
	mc.getConfigMapFn = func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) {
		return &corev1.ConfigMap{Data: map[string]string{"consoleURL": "https://console.example.com"}}, nil
	}
	url := GetConsoleURL(context.Background(), mc)
	if url != "https://console.example.com" {
		t.Errorf("url = %q, want %q", url, "https://console.example.com")
	}
}

func TestGetConsoleURL_NotFound(t *testing.T) {
	mc := noopClient()
	mc.getConfigMapFn = func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) {
		return nil, nil
	}
	url := GetConsoleURL(context.Background(), mc)
	if url != "" {
		t.Errorf("url = %q, want empty", url)
	}
}

func TestGetConsoleURL_ExceptionReturnsEmpty(t *testing.T) {
	mc := noopClient()
	mc.getConfigMapFn = func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) {
		return nil, fmt.Errorf("connection error")
	}
	url := GetConsoleURL(context.Background(), mc)
	if url != "" {
		t.Errorf("url = %q, want empty", url)
	}
}

func TestDescribeNamespace_NotFound(t *testing.T) {
	mc := noopClient()
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return nil, nil
	}
	_, err := DescribeNamespace(context.Background(), mc, "nonexistent")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "not found") {
		t.Errorf("error %q should contain 'not found'", err.Error())
	}
}

func TestDescribeNamespace_NotOperatorNs(t *testing.T) {
	mc := noopClient()
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return &corev1.Namespace{
			ObjectMeta: metav1.ObjectMeta{Name: "regular-ns", Labels: map[string]string{}},
		}, nil
	}
	_, err := DescribeNamespace(context.Background(), mc, "regular-ns")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "was not reserved") {
		t.Errorf("error %q should contain 'was not reserved'", err.Error())
	}
}

func TestDescribeNamespace_ComprehensiveOutput(t *testing.T) {
	mc := noopClient()
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return &corev1.Namespace{
			ObjectMeta: metav1.ObjectMeta{
				Name:   "ephemeral-test",
				Labels: map[string]string{"operator-ns": "true"},
			},
		}, nil
	}
	listCallCount := 0
	mc.listCRDsFn = func(_ context.Context, gvr schema.GroupVersionResource, _ string) ([]map[string]any, error) {
		listCallCount++
		if gvr.Resource == "clowdapps" {
			return []map[string]any{{"metadata": map[string]any{"name": "app1"}}, {"metadata": map[string]any{"name": "app2"}}}, nil
		}
		return []map[string]any{{"metadata": map[string]any{"name": "fe1"}}}, nil
	}
	mc.getCRDFn = func(_ context.Context, _ schema.GroupVersionResource, _, _ string) (map[string]any, error) {
		return map[string]any{
			"spec": map[string]any{
				"hostname": "test.example.com",
				"sso":      "https://keycloak.example.com",
			},
		}, nil
	}
	mc.getSecretFn = func(_ context.Context, name, _ string) (*corev1.Secret, error) {
		if strings.Contains(name, "keycloak") {
			return &corev1.Secret{
				Data: map[string][]byte{
					"username":        []byte("admin"),
					"password":        []byte("secret"),
					"defaultUsername": []byte("user1"),
					"defaultPassword": []byte("pass1"),
				},
			}, nil
		}
		return nil, nil
	}
	mc.getConfigMapFn = func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) {
		return &corev1.ConfigMap{Data: map[string]string{"consoleURL": "https://console.example.com"}}, nil
	}

	result, err := DescribeNamespace(context.Background(), mc, "ephemeral-test")
	mustNotErr(t, err)
	if result.Namespace != "ephemeral-test" {
		t.Errorf("Namespace = %q", result.Namespace)
	}
	if result.ClowdAppsDeployed != 2 {
		t.Errorf("ClowdAppsDeployed = %d, want 2", result.ClowdAppsDeployed)
	}
	if result.FrontendsDeployed != 1 {
		t.Errorf("FrontendsDeployed = %d, want 1", result.FrontendsDeployed)
	}
	if result.GatewayRoute != "https://test.example.com" {
		t.Errorf("GatewayRoute = %q", result.GatewayRoute)
	}
	if result.KeycloakAdminRoute != "https://keycloak.example.com" {
		t.Errorf("KeycloakAdminRoute = %q", result.KeycloakAdminRoute)
	}
	if !strings.Contains(result.ConsoleNamespaceRoute, "console.example.com") {
		t.Errorf("ConsoleNamespaceRoute = %q, should contain 'console.example.com'", result.ConsoleNamespaceRoute)
	}
}

func TestDescribeNamespace_NoKeycloakSecret(t *testing.T) {
	mc := noopClient()
	mc.getNamespaceFn = func(_ context.Context, _ string) (*corev1.Namespace, error) {
		return &corev1.Namespace{
			ObjectMeta: metav1.ObjectMeta{
				Name:   "ephemeral-test",
				Labels: map[string]string{"operator-ns": "true"},
			},
		}, nil
	}
	mc.listCRDsFn = func(_ context.Context, _ schema.GroupVersionResource, _ string) ([]map[string]any, error) {
		return []map[string]any{}, nil
	}
	mc.getCRDFn = func(_ context.Context, _ schema.GroupVersionResource, _, _ string) (map[string]any, error) {
		return nil, nil
	}
	mc.getSecretFn = func(_ context.Context, _, _ string) (*corev1.Secret, error) {
		return nil, nil
	}
	mc.getConfigMapFn = func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) {
		return nil, nil
	}

	result, err := DescribeNamespace(context.Background(), mc, "ephemeral-test")
	mustNotErr(t, err)
	if result.KeycloakAdminUsername != "N/A" {
		t.Errorf("KeycloakAdminUsername = %q, want N/A", result.KeycloakAdminUsername)
	}
	if result.GatewayRoute != "" {
		t.Errorf("GatewayRoute = %q, want empty", result.GatewayRoute)
	}
	if result.ConsoleNamespaceRoute != "" {
		t.Errorf("ConsoleNamespaceRoute = %q, want empty", result.ConsoleNamespaceRoute)
	}
}
