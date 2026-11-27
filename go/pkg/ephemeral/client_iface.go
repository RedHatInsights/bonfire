package ephemeral

import (
	"context"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// Client is the interface satisfied by EphemeralK8sClient.
// Domain functions (Reserve, Release, etc.) accept Client so they can be
// unit-tested without a live cluster.
type Client interface {
	// NamespaceReservation
	CreateReservation(ctx context.Context, body map[string]any) (map[string]any, error)
	GetReservation(ctx context.Context, name string) (map[string]any, error)
	ListReservations(ctx context.Context, labelSelector string) ([]map[string]any, error)
	PatchReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error)
	// NamespacePool
	ListPools(ctx context.Context) ([]map[string]any, error)
	GetPool(ctx context.Context, name string) (map[string]any, error)
	// ClusterReservation
	CreateClusterReservation(ctx context.Context, body map[string]any) (map[string]any, error)
	GetClusterReservation(ctx context.Context, name string) (map[string]any, error)
	ListClusterReservations(ctx context.Context, labelSelector string) ([]map[string]any, error)
	PatchClusterReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error)
	// ClusterPool
	ListClusterPools(ctx context.Context) ([]map[string]any, error)
	// Core
	GetNamespace(ctx context.Context, name string) (*corev1.Namespace, error)
	GetConfigMap(ctx context.Context, name, namespace string) (*corev1.ConfigMap, error)
	GetSecret(ctx context.Context, name, namespace string) (*corev1.Secret, error)
	ListCRDs(ctx context.Context, gvr schema.GroupVersionResource, namespace string) ([]map[string]any, error)
	GetCRD(ctx context.Context, gvr schema.GroupVersionResource, name, namespace string) (map[string]any, error)
	// Identity
	Whoami(ctx context.Context) string
}

// compile-time check that EphemeralK8sClient satisfies Client
var _ Client = (*EphemeralK8sClient)(nil)
