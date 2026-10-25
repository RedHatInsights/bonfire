// Package ephemeral provides the bonfire_lib Go port: namespace and cluster
// reservation lifecycle against cloud.redhat.com/v1alpha1 CRDs.
package ephemeral

import (
	"fmt"
	"regexp"
	"strconv"
)

// FatalError represents a logical error that should stop the caller.
type FatalError struct {
	msg string
}

func (e *FatalError) Error() string { return e.msg }

// NewFatalError creates a FatalError with the given message.
func NewFatalError(format string, args ...any) *FatalError {
	return &FatalError{msg: fmt.Sprintf(format, args...)}
}

var dnsLabelRE = regexp.MustCompile(`^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$`)

// ValidateDNSName validates that name conforms to DNS-1123 label rules.
// Rules: lowercase alphanumeric + hyphens, 1–63 chars, must start and end
// with alphanumeric. Returns the name unchanged if valid.
func ValidateDNSName(name string) (string, error) {
	if name == "" || !dnsLabelRE.MatchString(name) {
		return "", fmt.Errorf("invalid name %q: must be a DNS-1123 label (lowercase alphanumeric + hyphens, 1-63 chars)", name)
	}
	return name, nil
}

var durationRE = regexp.MustCompile(`^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$`)

// HMSToSeconds converts a duration string (e.g. "1h30m", "45m", "3600s") to seconds.
// Returns an error for empty or invalid strings. "0s" returns 0 without error.
func HMSToSeconds(s string) (int, error) {
	if s == "" {
		return 0, fmt.Errorf("duration string cannot be empty")
	}
	m := durationRE.FindStringSubmatch(s)
	if m == nil || (m[1] == "" && m[2] == "" && m[3] == "") {
		return 0, fmt.Errorf("invalid duration format: %q", s)
	}
	secs := 0
	if m[1] != "" {
		h, _ := strconv.Atoi(m[1])
		secs += h * 3600
	}
	if m[2] != "" {
		mn, _ := strconv.Atoi(m[2])
		secs += mn * 60
	}
	if m[3] != "" {
		sc, _ := strconv.Atoi(m[3])
		secs += sc
	}
	return secs, nil
}

// DurationFmt converts seconds to a duration string (e.g. "1h30m0s").
// This is the inverse of HMSToSeconds.
func DurationFmt(seconds int) string {
	h := seconds / 3600
	seconds %= 3600
	m := seconds / 60
	seconds %= 60
	if h > 0 {
		return fmt.Sprintf("%dh%dm%ds", h, m, seconds)
	} else if m > 0 {
		return fmt.Sprintf("%dm%ds", m, seconds)
	}
	return fmt.Sprintf("%ds", seconds)
}

// PrettyTimeDelta formats seconds as a human-readable delta (e.g. "2d3h15m0s").
func PrettyTimeDelta(seconds int) string {
	d := seconds / 86400
	seconds %= 86400
	h := seconds / 3600
	seconds %= 3600
	m := seconds / 60
	seconds %= 60
	if d > 0 {
		return fmt.Sprintf("%dd%dh%dm%ds", d, h, m, seconds)
	} else if h > 0 {
		return fmt.Sprintf("%dh%dm%ds", h, m, seconds)
	} else if m > 0 {
		return fmt.Sprintf("%dm%ds", m, seconds)
	}
	return fmt.Sprintf("%ds", seconds)
}

var validateFmt = regexp.MustCompile(`^((\d+)h)?((\d+)m)?((\d+)s)?$`)

const (
	minDurationSecs = 1800    // 30 minutes
	maxDurationSecs = 1209600 // 14 days
)

// ValidateTimeString validates a duration string format and range.
// Must be in h/m/s format (e.g. "1h30m"), between 30 minutes and 14 days.
func ValidateTimeString(s string) (string, error) {
	if !validateFmt.MatchString(s) {
		return "", fmt.Errorf("invalid format for duration %q, expecting h/m/s string. Ex: '1h30m'", s)
	}
	secs, err := HMSToSeconds(s)
	if err != nil {
		return "", fmt.Errorf("invalid format for duration %q, expecting h/m/s string. Ex: '1h30m'", s)
	}
	if secs > maxDurationSecs {
		return "", fmt.Errorf("invalid duration %q, must be less than 14 days", s)
	}
	if secs < minDurationSecs {
		return "", fmt.Errorf("invalid duration %q, must be more than 30 mins", s)
	}
	return s, nil
}

// sanitizeUsername replaces @ with _at_ and : with _ for use as a K8s label value.
func sanitizeUsername(name string) string {
	out := make([]byte, 0, len(name))
	for i := 0; i < len(name); i++ {
		switch name[i] {
		case '@':
			out = append(out, []byte("_at_")...)
		case ':':
			out = append(out, '_')
		default:
			out = append(out, name[i])
		}
	}
	return string(out)
}

// extractUsername extracts the username from a kubeconfig context user string.
// e.g. "gbuchana/api-crc-eph.com:6443" → "gbuchana"
func extractUsername(contextUser string) string {
	for i := 0; i < len(contextUser); i++ {
		if contextUser[i] == '/' {
			return contextUser[:i]
		}
	}
	return contextUser
}
