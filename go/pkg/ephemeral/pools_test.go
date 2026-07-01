package ephemeral

import (
	"context"
	"fmt"
	"testing"
)

func TestListPools_StructuredOutput(t *testing.T) {
	mc := noopClient()
	mc.listPoolsFn = func(_ context.Context) ([]map[string]any, error) {
		return []map[string]any{samplePool()}, nil
	}

	result, err := ListPools(context.Background(), mc)
	mustNotErr(t, err)
	if len(result) != 1 {
		t.Fatalf("len = %d, want 1", len(result))
	}
	p := result[0]
	if p.Name != "default" {
		t.Errorf("Name = %q, want %q", p.Name, "default")
	}
	if p.Description != "Default pool" {
		t.Errorf("Description = %q, want %q", p.Description, "Default pool")
	}
	if p.Size != 5 {
		t.Errorf("Size = %d, want 5", p.Size)
	}
	if p.SizeLimit == nil || *p.SizeLimit != 10 {
		t.Errorf("SizeLimit = %v, want 10", p.SizeLimit)
	}
	if p.Ready != 3 {
		t.Errorf("Ready = %d, want 3", p.Ready)
	}
	if p.Creating != 1 {
		t.Errorf("Creating = %d, want 1", p.Creating)
	}
	if p.Reserved != 2 {
		t.Errorf("Reserved = %d, want 2", p.Reserved)
	}
}

func TestListPools_Empty(t *testing.T) {
	mc := noopClient()
	mc.listPoolsFn = func(_ context.Context) ([]map[string]any, error) {
		return []map[string]any{}, nil
	}
	result, err := ListPools(context.Background(), mc)
	mustNotErr(t, err)
	if len(result) != 0 {
		t.Errorf("len = %d, want 0", len(result))
	}
}

func TestListPools_MissingOptionalFields(t *testing.T) {
	mc := noopClient()
	mc.listPoolsFn = func(_ context.Context) ([]map[string]any, error) {
		return []map[string]any{{
			"metadata": map[string]any{"name": "sparse"},
			"spec":     map[string]any{},
			"status":   map[string]any{},
		}}, nil
	}
	result, err := ListPools(context.Background(), mc)
	mustNotErr(t, err)
	p := result[0]
	if p.Description != "" {
		t.Errorf("Description = %q, want empty", p.Description)
	}
	if p.Size != 0 {
		t.Errorf("Size = %d, want 0", p.Size)
	}
	if p.SizeLimit != nil {
		t.Errorf("SizeLimit = %v, want nil", p.SizeLimit)
	}
	if p.Ready != 0 || p.Creating != 0 || p.Reserved != 0 {
		t.Error("expected all status counters to be 0")
	}
}

func TestListPools_Multiple(t *testing.T) {
	pool2 := map[string]any{
		"metadata": map[string]any{"name": "minimal"},
		"spec":     map[string]any{"size": float64(2), "description": "Minimal pool"},
		"status":   map[string]any{"ready": float64(1), "creating": float64(0), "reserved": float64(1)},
	}
	mc := noopClient()
	mc.listPoolsFn = func(_ context.Context) ([]map[string]any, error) {
		return []map[string]any{samplePool(), pool2}, nil
	}
	result, err := ListPools(context.Background(), mc)
	mustNotErr(t, err)
	if len(result) != 2 {
		t.Fatalf("len = %d, want 2", len(result))
	}
	if result[0].Name != "default" || result[1].Name != "minimal" {
		t.Errorf("names = %q, %q; want 'default', 'minimal'", result[0].Name, result[1].Name)
	}
}

func TestGetPoolCapacity_Existing(t *testing.T) {
	mc := noopClient()
	mc.getPoolFn = func(_ context.Context, _ string) (map[string]any, error) {
		return samplePool(), nil
	}
	result, err := GetPoolCapacity(context.Background(), mc, "default")
	mustNotErr(t, err)
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	if result.Name != "default" {
		t.Errorf("Name = %q, want %q", result.Name, "default")
	}
	if result.Size != 5 {
		t.Errorf("Size = %d, want 5", result.Size)
	}
}

func TestGetPoolCapacity_Nonexistent(t *testing.T) {
	mc := noopClient()
	mc.getPoolFn = func(_ context.Context, _ string) (map[string]any, error) {
		return nil, nil
	}
	result, err := GetPoolCapacity(context.Background(), mc, "nonexistent")
	mustNotErr(t, err)
	if result != nil {
		t.Errorf("expected nil result, got %v", result)
	}
}

func TestListClusterPools_CRDNotAvailable(t *testing.T) {
	mc := noopClient()
	mc.listClusterPoolsFn = func(_ context.Context) ([]map[string]any, error) {
		return nil, fmt.Errorf("CRD not found")
	}
	result, err := ListClusterPools(context.Background(), mc)
	mustNotErr(t, err) // should swallow the error
	if len(result) != 0 {
		t.Errorf("len = %d, want 0", len(result))
	}
}
