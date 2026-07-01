package ephemeral

import (
	"context"
	"log/slog"
)

// PoolInfo holds capacity information for a namespace pool.
type PoolInfo struct {
	Name        string
	Description string
	Size        int64
	SizeLimit   *int64 // nil means unlimited
	Ready       int64
	Creating    int64
	Reserved    int64
}

// ClusterPoolInfo holds capacity information for a cluster pool.
type ClusterPoolInfo struct {
	Name         string
	Description  string
	Size         int64
	SizeLimit    int64
	Ready        int64
	Provisioning int64
	Reserved     int64
}

// ListPools lists all namespace pools with capacity stats.
// Mirrors bonfire_lib/pools.py:list_pools().
func ListPools(ctx context.Context, client Client) ([]PoolInfo, error) {
	pools, err := client.ListPools(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]PoolInfo, 0, len(pools))
	for _, pool := range pools {
		spec := nestedMap(pool, "spec")
		status := nestedMap(pool, "status")
		if spec == nil {
			spec = map[string]any{}
		}
		if status == nil {
			status = map[string]any{}
		}

		info := PoolInfo{
			Name:        nestedString(pool, "metadata", "name"),
			Description: nestedString(spec, "description"),
			Size:        nestedInt64(spec, "size"),
			Ready:       nestedInt64(status, "ready"),
			Creating:    nestedInt64(status, "creating"),
			Reserved:    nestedInt64(status, "reserved"),
		}
		if sl, ok := spec["sizeLimit"]; ok && sl != nil {
			v := nestedInt64(spec, "sizeLimit")
			info.SizeLimit = &v
		}
		out = append(out, info)
	}
	return out, nil
}

// GetPoolCapacity returns capacity details for a specific pool.
// Returns nil, nil if pool not found.
// Mirrors bonfire_lib/pools.py:get_pool_capacity().
func GetPoolCapacity(ctx context.Context, client Client, poolName string) (*PoolInfo, error) {
	pool, err := client.GetPool(ctx, poolName)
	if err != nil {
		return nil, err
	}
	if pool == nil {
		return nil, nil
	}
	spec := nestedMap(pool, "spec")
	status := nestedMap(pool, "status")
	if spec == nil {
		spec = map[string]any{}
	}
	if status == nil {
		status = map[string]any{}
	}
	info := &PoolInfo{
		Name:        poolName,
		Description: nestedString(spec, "description"),
		Size:        nestedInt64(spec, "size"),
		Ready:       nestedInt64(status, "ready"),
		Creating:    nestedInt64(status, "creating"),
		Reserved:    nestedInt64(status, "reserved"),
	}
	if sl, ok := spec["sizeLimit"]; ok && sl != nil {
		v := nestedInt64(spec, "sizeLimit")
		info.SizeLimit = &v
	}
	return info, nil
}

// ListClusterPools lists all cluster pools with capacity stats.
// Returns an empty slice if the ClusterPool CRD is not installed.
// Mirrors bonfire_lib/pools.py:list_cluster_pools().
func ListClusterPools(ctx context.Context, client Client) ([]ClusterPoolInfo, error) {
	pools, err := client.ListClusterPools(ctx)
	if err != nil {
		slog.Debug("ClusterPool CRD not available, skipping cluster pools", "err", err)
		return []ClusterPoolInfo{}, nil
	}
	out := make([]ClusterPoolInfo, 0, len(pools))
	for _, pool := range pools {
		spec := nestedMap(pool, "spec")
		status := nestedMap(pool, "status")
		if spec == nil {
			spec = map[string]any{}
		}
		if status == nil {
			status = map[string]any{}
		}
		out = append(out, ClusterPoolInfo{
			Name:         nestedString(pool, "metadata", "name"),
			Description:  nestedString(spec, "description"),
			Size:         nestedInt64(spec, "size"),
			SizeLimit:    nestedInt64(spec, "sizeLimit"),
			Ready:        nestedInt64(status, "ready"),
			Provisioning: nestedInt64(status, "provisioning"),
			Reserved:     nestedInt64(status, "reserved"),
		})
	}
	return out, nil
}

// AllPools holds both namespace and cluster pool lists.
type AllPools struct {
	NamespacePools []PoolInfo
	ClusterPools   []ClusterPoolInfo
}

// ListAllPools lists both namespace and cluster pools.
// Mirrors bonfire_lib/pools.py:list_all_pools().
func ListAllPools(ctx context.Context, client Client) (*AllPools, error) {
	ns, err := ListPools(ctx, client)
	if err != nil {
		return nil, err
	}
	cl, err := ListClusterPools(ctx, client)
	if err != nil {
		return nil, err
	}
	return &AllPools{NamespacePools: ns, ClusterPools: cl}, nil
}
