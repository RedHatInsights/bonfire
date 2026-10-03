package ephemeral

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// compile-time check: testClient satisfies the exported Client interface
var _ Client = (*testClient)(nil)

// testClient is a test double for Client.
type testClient struct {
	createReservationFn        func(ctx context.Context, body map[string]any) (map[string]any, error)
	getReservationFn           func(ctx context.Context, name string) (map[string]any, error)
	listReservationsFn         func(ctx context.Context, labelSelector string) ([]map[string]any, error)
	patchReservationFn         func(ctx context.Context, name string, patch map[string]any) (map[string]any, error)
	listPoolsFn                func(ctx context.Context) ([]map[string]any, error)
	getPoolFn                  func(ctx context.Context, name string) (map[string]any, error)
	createClusterReservationFn func(ctx context.Context, body map[string]any) (map[string]any, error)
	getClusterReservationFn    func(ctx context.Context, name string) (map[string]any, error)
	listClusterReservationsFn  func(ctx context.Context, labelSelector string) ([]map[string]any, error)
	patchClusterReservationFn  func(ctx context.Context, name string, patch map[string]any) (map[string]any, error)
	listClusterPoolsFn         func(ctx context.Context) ([]map[string]any, error)
	getNamespaceFn             func(ctx context.Context, name string) (*corev1.Namespace, error)
	getConfigMapFn             func(ctx context.Context, name, namespace string) (*corev1.ConfigMap, error)
	getSecretFn                func(ctx context.Context, name, namespace string) (*corev1.Secret, error)
	listCRDsFn                 func(ctx context.Context, gvr schema.GroupVersionResource, namespace string) ([]map[string]any, error)
	getCRDFn                   func(ctx context.Context, gvr schema.GroupVersionResource, name, namespace string) (map[string]any, error)
	whoamiFn                   func(ctx context.Context) string
}

func (m *testClient) CreateReservation(ctx context.Context, body map[string]any) (map[string]any, error) {
	return m.createReservationFn(ctx, body)
}
func (m *testClient) GetReservation(ctx context.Context, name string) (map[string]any, error) {
	return m.getReservationFn(ctx, name)
}
func (m *testClient) ListReservations(ctx context.Context, sel string) ([]map[string]any, error) {
	return m.listReservationsFn(ctx, sel)
}
func (m *testClient) PatchReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error) {
	return m.patchReservationFn(ctx, name, patch)
}
func (m *testClient) ListPools(ctx context.Context) ([]map[string]any, error) {
	return m.listPoolsFn(ctx)
}
func (m *testClient) GetPool(ctx context.Context, name string) (map[string]any, error) {
	return m.getPoolFn(ctx, name)
}
func (m *testClient) CreateClusterReservation(ctx context.Context, body map[string]any) (map[string]any, error) {
	return m.createClusterReservationFn(ctx, body)
}
func (m *testClient) GetClusterReservation(ctx context.Context, name string) (map[string]any, error) {
	return m.getClusterReservationFn(ctx, name)
}
func (m *testClient) ListClusterReservations(ctx context.Context, sel string) ([]map[string]any, error) {
	return m.listClusterReservationsFn(ctx, sel)
}
func (m *testClient) PatchClusterReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error) {
	return m.patchClusterReservationFn(ctx, name, patch)
}
func (m *testClient) ListClusterPools(ctx context.Context) ([]map[string]any, error) {
	return m.listClusterPoolsFn(ctx)
}
func (m *testClient) GetNamespace(ctx context.Context, name string) (*corev1.Namespace, error) {
	return m.getNamespaceFn(ctx, name)
}
func (m *testClient) GetConfigMap(ctx context.Context, name, ns string) (*corev1.ConfigMap, error) {
	return m.getConfigMapFn(ctx, name, ns)
}
func (m *testClient) GetSecret(ctx context.Context, name, ns string) (*corev1.Secret, error) {
	return m.getSecretFn(ctx, name, ns)
}
func (m *testClient) ListCRDs(ctx context.Context, gvr schema.GroupVersionResource, ns string) ([]map[string]any, error) {
	return m.listCRDsFn(ctx, gvr, ns)
}
func (m *testClient) GetCRD(ctx context.Context, gvr schema.GroupVersionResource, name, ns string) (map[string]any, error) {
	return m.getCRDFn(ctx, gvr, name, ns)
}
func (m *testClient) Whoami(ctx context.Context) string {
	if m.whoamiFn != nil {
		return m.whoamiFn(ctx)
	}
	return "test_at_user.com"
}

// sampleReservation returns a realistic NamespaceReservation CR dict.
func sampleReservation() map[string]any {
	return map[string]any{
		"apiVersion": "cloud.redhat.com/v1alpha1",
		"kind":       "NamespaceReservation",
		"metadata": map[string]any{
			"name":   "test-reservation",
			"labels": map[string]any{"requester": "test-user"},
		},
		"spec": map[string]any{
			"duration":  "1h",
			"requester": "test-user",
			"pool":      "default",
		},
		"status": map[string]any{
			"state":      "active",
			"namespace":  "ephemeral-abc123",
			"expiration": "2026-04-09T12:00:00Z",
			"pool":       "default",
		},
	}
}

// samplePool returns a realistic NamespacePool CR dict.
func samplePool() map[string]any {
	return map[string]any{
		"apiVersion": "cloud.redhat.com/v1alpha1",
		"kind":       "NamespacePool",
		"metadata":   map[string]any{"name": "default"},
		"spec": map[string]any{
			"size":        float64(5),
			"sizeLimit":   float64(10),
			"description": "Default pool",
		},
		"status": map[string]any{
			"ready":    float64(3),
			"creating": float64(1),
			"reserved": float64(2),
		},
	}
}

// mustNotErr fails the test if err is non-nil.
func mustNotErr(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// noopFns returns a testClient with all functions stubbed to return zero values.
// Override individual fields in each test.
func noopClient() *testClient {
	return &testClient{
		createReservationFn:        func(_ context.Context, _ map[string]any) (map[string]any, error) { return nil, nil },
		getReservationFn:           func(_ context.Context, _ string) (map[string]any, error) { return nil, nil },
		listReservationsFn:         func(_ context.Context, _ string) ([]map[string]any, error) { return nil, nil },
		patchReservationFn:         func(_ context.Context, _ string, _ map[string]any) (map[string]any, error) { return nil, nil },
		listPoolsFn:                func(_ context.Context) ([]map[string]any, error) { return nil, nil },
		getPoolFn:                  func(_ context.Context, _ string) (map[string]any, error) { return nil, nil },
		createClusterReservationFn: func(_ context.Context, _ map[string]any) (map[string]any, error) { return nil, nil },
		getClusterReservationFn:    func(_ context.Context, _ string) (map[string]any, error) { return nil, nil },
		listClusterReservationsFn:  func(_ context.Context, _ string) ([]map[string]any, error) { return nil, nil },
		patchClusterReservationFn:  func(_ context.Context, _ string, _ map[string]any) (map[string]any, error) { return nil, nil },
		listClusterPoolsFn:         func(_ context.Context) ([]map[string]any, error) { return nil, nil },
		getNamespaceFn:             func(_ context.Context, _ string) (*corev1.Namespace, error) { return nil, nil },
		getConfigMapFn:             func(_ context.Context, _, _ string) (*corev1.ConfigMap, error) { return nil, nil },
		getSecretFn:                func(_ context.Context, _, _ string) (*corev1.Secret, error) { return nil, nil },
		listCRDsFn:                 func(_ context.Context, _ schema.GroupVersionResource, _ string) ([]map[string]any, error) { return nil, nil },
		getCRDFn:                   func(_ context.Context, _ schema.GroupVersionResource, _, _ string) (map[string]any, error) { return nil, nil },
	}
}
