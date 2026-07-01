package ephemeral

import (
	"context"
	"encoding/base64"
	"fmt"
	"log/slog"
	"os"

	authv1 "k8s.io/api/authentication/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

const (
	crdGroup   = "cloud.redhat.com"
	crdVersion = "v1alpha1"

	kindNamespaceReservation = "NamespaceReservation"
	kindNamespacePool        = "NamespacePool"
	kindClusterReservation   = "ClusterReservation"
	kindClusterPool          = "ClusterPool"
	kindClowdApp             = "ClowdApp"
	kindFrontend             = "Frontend"
	kindFrontendEnvironment  = "FrontendEnvironment"

	defaultReadTimeout  = 30
	defaultWriteTimeout = 60
)

var (
	gvrNamespaceReservation = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "namespacereservations"}
	gvrNamespacePool        = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "namespacepools"}
	gvrClusterReservation   = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "clusterreservations"}
	gvrClusterPool          = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "clusterpools"}
	gvrClowdApp             = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "clowdapps"}
	gvrFrontend             = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "frontends"}
	gvrFrontendEnvironment  = schema.GroupVersionResource{Group: crdGroup, Version: crdVersion, Resource: "frontendenvironments"}
)

// AuthMode describes how the client authenticated to the cluster.
type AuthMode string

const (
	AuthModeToken     AuthMode = "token"
	AuthModeInCluster AuthMode = "in-cluster"
	AuthModeKubeconfig AuthMode = "kubeconfig"
)

// ClientOptions holds optional parameters for NewClient.
type ClientOptions struct {
	// KubeconfigPath overrides the default kubeconfig file location.
	KubeconfigPath string
	// Context selects a specific kubeconfig context.
	Context string
	// Server is the API server URL for explicit token auth.
	Server string
	// Token is the bearer token for explicit token auth.
	Token string
	// CAData is base64-encoded CA certificate data for token auth.
	CAData string
	// SkipTLS disables TLS verification (token auth only).
	SkipTLS bool
}

// EphemeralK8sClient is the Kubernetes API client for ephemeral resource CRDs.
// It mirrors bonfire_lib/k8s_client.py:EphemeralK8sClient.
//
// Auth modes (auto-detected in priority order):
//  1. Explicit Server + Token (ClientOptions.Server + ClientOptions.Token)
//  2. In-cluster service account (/var/run/secrets/kubernetes.io/serviceaccount/token)
//  3. Kubeconfig file (KUBECONFIG env var or ~/.kube/config)
type EphemeralK8sClient struct {
	authMode   AuthMode
	dynamic    dynamic.Interface
	core       kubernetes.Interface
	restConfig *rest.Config
}

// NewClient creates an EphemeralK8sClient using the provided options.
// Auth mode is selected in the priority order documented on EphemeralK8sClient.
func NewClient(opts ClientOptions) (*EphemeralK8sClient, error) {
	var cfg *rest.Config
	var authMode AuthMode
	var err error

	if opts.Server != "" && opts.Token != "" {
		// Priority 1: explicit server + token
		authMode = AuthModeToken
		cfg = &rest.Config{
			Host:        opts.Server,
			BearerToken: opts.Token,
		}
		if opts.SkipTLS {
			cfg.TLSClientConfig = rest.TLSClientConfig{Insecure: true}
		} else if opts.CAData != "" {
			caBytes, err2 := base64.StdEncoding.DecodeString(opts.CAData)
			if err2 != nil {
				return nil, fmt.Errorf("invalid CA data: %w", err2)
			}
			cfg.TLSClientConfig = rest.TLSClientConfig{CAData: caBytes}
		}
	} else {
		// Try kubeconfig first (Priority 3), fall back to in-cluster (Priority 2).
		// This mirrors the Python behaviour: prefer explicit oc-login credentials even
		// when running inside a pod (e.g. GitLab CI runners).
		loadRules := clientcmd.NewDefaultClientConfigLoadingRules()
		if opts.KubeconfigPath != "" {
			loadRules.ExplicitPath = opts.KubeconfigPath
		}
		overrides := &clientcmd.ConfigOverrides{}
		if opts.Context != "" {
			overrides.CurrentContext = opts.Context
		}
		kubeConfig := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadRules, overrides)
		cfg, err = kubeConfig.ClientConfig()
		if err != nil {
			// Kubeconfig failed — try in-cluster
			if isInCluster() {
				slog.Warn("kubeconfig auth failed, attempting in-cluster fallback", "err", err)
				cfg, err = rest.InClusterConfig()
				if err != nil {
					return nil, fmt.Errorf("both kubeconfig and in-cluster auth failed: %w", err)
				}
				authMode = AuthModeInCluster
			} else {
				return nil, fmt.Errorf("unable to load kubeconfig and not running in-cluster: %w", err)
			}
		} else {
			authMode = AuthModeKubeconfig
			// Verify the kubeconfig actually works by hitting /api
			testClient, err2 := kubernetes.NewForConfig(cfg)
			if err2 != nil {
				return nil, fmt.Errorf("failed to build k8s client: %w", err2)
			}
			if _, err2 = testClient.CoreV1().Namespaces().List(context.Background(), metav1.ListOptions{Limit: 1}); err2 != nil {
				if isInCluster() {
					slog.Warn("kubeconfig connectivity check failed, attempting in-cluster fallback", "err", err2)
					cfg, err = rest.InClusterConfig()
					if err != nil {
						return nil, fmt.Errorf("both kubeconfig and in-cluster auth failed: %w", err)
					}
					authMode = AuthModeInCluster
				} else {
					return nil, fmt.Errorf("kubeconfig auth failed: %w", err2)
				}
			}
		}
	}

	dynClient, err := dynamic.NewForConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("failed to create dynamic client: %w", err)
	}
	coreClient, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("failed to create core client: %w", err)
	}

	return &EphemeralK8sClient{
		authMode:   authMode,
		dynamic:    dynClient,
		core:       coreClient,
		restConfig: cfg,
	}, nil
}

// isInCluster returns true if running inside a Kubernetes pod.
func isInCluster() bool {
	_, err := os.Stat("/var/run/secrets/kubernetes.io/serviceaccount/token")
	return err == nil
}

// AuthMode returns the auth mode used by this client.
func (c *EphemeralK8sClient) AuthMode() AuthMode { return c.authMode }

// --- helpers ---

func ignoreNotFound(err error) error {
	if errors.IsNotFound(err) {
		return nil
	}
	return err
}

func (c *EphemeralK8sClient) gvrResource(gvr schema.GroupVersionResource) dynamic.ResourceInterface {
	return c.dynamic.Resource(gvr)
}

func (c *EphemeralK8sClient) gvrNamespacedResource(gvr schema.GroupVersionResource, namespace string) dynamic.ResourceInterface {
	return c.dynamic.Resource(gvr).Namespace(namespace)
}

// --- NamespaceReservation operations ---

// CreateReservation creates a NamespaceReservation CR.
func (c *EphemeralK8sClient) CreateReservation(ctx context.Context, body map[string]any) (map[string]any, error) {
	obj := &unstructured.Unstructured{Object: body}
	result, err := c.gvrResource(gvrNamespaceReservation).Create(ctx, obj, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("create NamespaceReservation: %w", err)
	}
	return result.Object, nil
}

// GetReservation returns a NamespaceReservation by name. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetReservation(ctx context.Context, name string) (map[string]any, error) {
	result, err := c.gvrResource(gvrNamespaceReservation).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, ignoreNotFound(err)
	}
	return result.Object, nil
}

// ListReservations lists all NamespaceReservation CRs, optionally filtered by labelSelector.
func (c *EphemeralK8sClient) ListReservations(ctx context.Context, labelSelector string) ([]map[string]any, error) {
	opts := metav1.ListOptions{LabelSelector: labelSelector}
	list, err := c.gvrResource(gvrNamespaceReservation).List(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("list NamespaceReservations: %w", err)
	}
	return unstructuredItems(list), nil
}

// PatchReservation applies a merge patch to a NamespaceReservation.
func (c *EphemeralK8sClient) PatchReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error) {
	data, err := marshalJSON(patch)
	if err != nil {
		return nil, err
	}
	result, err := c.gvrResource(gvrNamespaceReservation).Patch(ctx, name, types.MergePatchType, data, metav1.PatchOptions{})
	if err != nil {
		return nil, fmt.Errorf("patch NamespaceReservation %q: %w", name, err)
	}
	return result.Object, nil
}

// --- NamespacePool operations ---

// ListPools lists all NamespacePool CRs.
func (c *EphemeralK8sClient) ListPools(ctx context.Context) ([]map[string]any, error) {
	list, err := c.gvrResource(gvrNamespacePool).List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("list NamespacePools: %w", err)
	}
	return unstructuredItems(list), nil
}

// GetPool returns a NamespacePool by name. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetPool(ctx context.Context, name string) (map[string]any, error) {
	result, err := c.gvrResource(gvrNamespacePool).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, ignoreNotFound(err)
	}
	return result.Object, nil
}

// --- ClusterReservation operations ---

// CreateClusterReservation creates a ClusterReservation CR.
func (c *EphemeralK8sClient) CreateClusterReservation(ctx context.Context, body map[string]any) (map[string]any, error) {
	obj := &unstructured.Unstructured{Object: body}
	result, err := c.gvrResource(gvrClusterReservation).Create(ctx, obj, metav1.CreateOptions{})
	if err != nil {
		return nil, fmt.Errorf("create ClusterReservation: %w", err)
	}
	return result.Object, nil
}

// GetClusterReservation returns a ClusterReservation by name. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetClusterReservation(ctx context.Context, name string) (map[string]any, error) {
	result, err := c.gvrResource(gvrClusterReservation).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, ignoreNotFound(err)
	}
	return result.Object, nil
}

// ListClusterReservations lists all ClusterReservation CRs, optionally filtered by labelSelector.
func (c *EphemeralK8sClient) ListClusterReservations(ctx context.Context, labelSelector string) ([]map[string]any, error) {
	opts := metav1.ListOptions{LabelSelector: labelSelector}
	list, err := c.gvrResource(gvrClusterReservation).List(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("list ClusterReservations: %w", err)
	}
	return unstructuredItems(list), nil
}

// PatchClusterReservation applies a merge patch to a ClusterReservation.
func (c *EphemeralK8sClient) PatchClusterReservation(ctx context.Context, name string, patch map[string]any) (map[string]any, error) {
	data, err := marshalJSON(patch)
	if err != nil {
		return nil, err
	}
	result, err := c.gvrResource(gvrClusterReservation).Patch(ctx, name, types.MergePatchType, data, metav1.PatchOptions{})
	if err != nil {
		return nil, fmt.Errorf("patch ClusterReservation %q: %w", name, err)
	}
	return result.Object, nil
}

// --- ClusterPool operations ---

// ListClusterPools lists all ClusterPool CRs.
func (c *EphemeralK8sClient) ListClusterPools(ctx context.Context) ([]map[string]any, error) {
	list, err := c.gvrResource(gvrClusterPool).List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("list ClusterPools: %w", err)
	}
	return unstructuredItems(list), nil
}

// GetClusterPool returns a ClusterPool by name. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetClusterPool(ctx context.Context, name string) (map[string]any, error) {
	result, err := c.gvrResource(gvrClusterPool).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, ignoreNotFound(err)
	}
	return result.Object, nil
}

// --- Namespace operations (CoreV1Api) ---

// GetNamespace returns a namespace by name. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetNamespace(ctx context.Context, name string) (*corev1.Namespace, error) {
	ns, err := c.core.CoreV1().Namespaces().Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("get namespace %q: %w", name, err)
	}
	return ns, nil
}

// GetConfigMap returns a ConfigMap by name and namespace. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetConfigMap(ctx context.Context, name, namespace string) (*corev1.ConfigMap, error) {
	cm, err := c.core.CoreV1().ConfigMaps(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("get configmap %q/%q: %w", namespace, name, err)
	}
	return cm, nil
}

// GetSecret returns a Secret by name and namespace. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetSecret(ctx context.Context, name, namespace string) (*corev1.Secret, error) {
	secret, err := c.core.CoreV1().Secrets(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("get secret %q/%q: %w", namespace, name, err)
	}
	return secret, nil
}

// --- Generic CRD operations ---

// ListCRDs lists CRDs of a given GVR, optionally scoped to a namespace.
func (c *EphemeralK8sClient) ListCRDs(ctx context.Context, gvr schema.GroupVersionResource, namespace string) ([]map[string]any, error) {
	var ri dynamic.ResourceInterface
	if namespace != "" {
		ri = c.dynamic.Resource(gvr).Namespace(namespace)
	} else {
		ri = c.dynamic.Resource(gvr)
	}
	list, err := ri.List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("list %s: %w", gvr.Resource, err)
	}
	return unstructuredItems(list), nil
}

// GetCRD returns a single CRD by GVR and name, optionally in a namespace. Returns nil, nil if not found.
func (c *EphemeralK8sClient) GetCRD(ctx context.Context, gvr schema.GroupVersionResource, name, namespace string) (map[string]any, error) {
	var ri dynamic.ResourceInterface
	if namespace != "" {
		ri = c.dynamic.Resource(gvr).Namespace(namespace)
	} else {
		ri = c.dynamic.Resource(gvr)
	}
	result, err := ri.Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, ignoreNotFound(err)
	}
	return result.Object, nil
}

// --- Identity ---

// Whoami returns the current authenticated user identity, sanitized for use
// as a K8s label value (@ → _at_, : → _).
// Falls back to "unknown" if identity cannot be determined.
func (c *EphemeralK8sClient) Whoami(ctx context.Context) string {
	if c.authMode == AuthModeKubeconfig {
		loadRules := clientcmd.NewDefaultClientConfigLoadingRules()
		kubeConfig := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadRules, &clientcmd.ConfigOverrides{})
		rawConfig, err := kubeConfig.RawConfig()
		if err == nil {
			if contextName := rawConfig.CurrentContext; contextName != "" {
				if ctx2, ok := rawConfig.Contexts[contextName]; ok && ctx2 != nil {
					user := ctx2.AuthInfo
					if user != "" {
						return sanitizeUsername(extractUsername(user))
					}
				}
			}
		}
	}

	// Token review for token/in-cluster modes
	token := c.restConfig.BearerToken
	if token == "" {
		return "unknown"
	}
	review, err := c.core.AuthenticationV1().TokenReviews().Create(ctx, &authv1.TokenReview{
		Spec: authv1.TokenReviewSpec{Token: token},
	}, metav1.CreateOptions{})
	if err != nil {
		slog.Debug("whoami token review failed", "err", err)
		return "unknown"
	}
	if review.Status.User.Username != "" {
		return sanitizeUsername(review.Status.User.Username)
	}
	return "unknown"
}

// --- internal helpers ---

func unstructuredItems(list *unstructured.UnstructuredList) []map[string]any {
	out := make([]map[string]any, len(list.Items))
	for i, item := range list.Items {
		out[i] = item.Object
	}
	return out
}
