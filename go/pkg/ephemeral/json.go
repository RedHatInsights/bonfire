package ephemeral

import "encoding/json"

// marshalJSON encodes v to JSON bytes. Used internally for patch bodies.
func marshalJSON(v any) ([]byte, error) {
	return json.Marshal(v)
}

// nestedString is a helper to safely extract a nested string from an
// unstructured map without panicking on nil or missing keys.
// path is a sequence of map keys to traverse.
func nestedString(obj map[string]any, path ...string) string {
	cur := obj
	for i, key := range path {
		val, ok := cur[key]
		if !ok {
			return ""
		}
		if i == len(path)-1 {
			s, _ := val.(string)
			return s
		}
		cur, ok = val.(map[string]any)
		if !ok {
			return ""
		}
	}
	return ""
}

// nestedInt64 safely extracts a nested int64 (or numeric) value.
func nestedInt64(obj map[string]any, path ...string) int64 {
	cur := obj
	for i, key := range path {
		val, ok := cur[key]
		if !ok {
			return 0
		}
		if i == len(path)-1 {
			switch v := val.(type) {
			case int64:
				return v
			case int:
				return int64(v)
			case float64:
				return int64(v)
			}
			return 0
		}
		cur, ok = val.(map[string]any)
		if !ok {
			return 0
		}
	}
	return 0
}

// nestedMap safely extracts a nested map[string]any.
func nestedMap(obj map[string]any, path ...string) map[string]any {
	cur := obj
	for _, key := range path {
		val, ok := cur[key]
		if !ok {
			return nil
		}
		m, ok := val.(map[string]any)
		if !ok {
			return nil
		}
		cur = m
	}
	return cur
}
