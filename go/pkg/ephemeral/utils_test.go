package ephemeral

import (
	"testing"
)

func TestSanitizeUsername(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{"at sign", "user@redhat.com", "user_at_redhat.com"},
		{"colon", "system:admin", "system_admin"},
		{"both", "u@r:c", "u_at_r_c"},
		{"no change", "plainuser", "plainuser"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := sanitizeUsername(tt.input); got != tt.want {
				t.Errorf("sanitizeUsername(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}

func TestExtractUsername(t *testing.T) {
	tests := []struct {
		name        string
		contextUser string
		want        string
	}{
		{"with cluster url", "gbuchana/api-crc-eph-r9lp-p1-openshiftapps-com:6443", "gbuchana"},
		{"simple url", "admin/api.example.com:6443", "admin"},
		{"plain username", "gbuchana", "gbuchana"},
		{"email style", "user@redhat.com", "user@redhat.com"},
		{"multiple slashes", "user/host/extra", "user"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := extractUsername(tt.contextUser); got != tt.want {
				t.Errorf("extractUsername(%q) = %q, want %q", tt.contextUser, got, tt.want)
			}
		})
	}
}

func TestHMSToSeconds(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		want    int
		wantErr bool
	}{
		{"hours only", "1h", 3600, false},
		{"minutes only", "30m", 1800, false},
		{"seconds only", "90s", 90, false},
		{"hours and minutes", "1h30m", 5400, false},
		{"all units", "1h0m30s", 3630, false},
		{"zero", "0s", 0, false},
		{"large", "24h", 86400, false},
		{"empty string", "", 0, true},
		{"invalid", "abc", 0, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := HMSToSeconds(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("HMSToSeconds(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
				return
			}
			if !tt.wantErr && got != tt.want {
				t.Errorf("HMSToSeconds(%q) = %d, want %d", tt.input, got, tt.want)
			}
		})
	}
}

func TestDurationFmt(t *testing.T) {
	tests := []struct {
		name    string
		seconds int
		want    string
	}{
		{"hours minutes seconds", 5400, "1h30m0s"},
		{"minutes seconds", 90, "1m30s"},
		{"seconds only", 45, "45s"},
		{"zero", 0, "0s"},
		{"exact hour", 3600, "1h0m0s"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := DurationFmt(tt.seconds); got != tt.want {
				t.Errorf("DurationFmt(%d) = %q, want %q", tt.seconds, got, tt.want)
			}
		})
	}
}

func TestDurationRoundtrip(t *testing.T) {
	secs := 5400
	formatted := DurationFmt(secs)
	got, err := HMSToSeconds(formatted)
	if err != nil {
		t.Fatalf("HMSToSeconds(%q) error: %v", formatted, err)
	}
	if got != secs {
		t.Errorf("roundtrip failed: %d → %q → %d", secs, formatted, got)
	}
}

func TestPrettyTimeDelta(t *testing.T) {
	tests := []struct {
		name    string
		seconds int
		want    string
	}{
		{"with days", 90061, "1d1h1m1s"},
		{"hours", 3661, "1h1m1s"},
		{"minutes", 61, "1m1s"},
		{"seconds", 5, "5s"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := PrettyTimeDelta(tt.seconds); got != tt.want {
				t.Errorf("PrettyTimeDelta(%d) = %q, want %q", tt.seconds, got, tt.want)
			}
		})
	}
}

func TestValidateDNSName(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		{"valid hyphen", "my-reservation", false},
		{"valid alnum", "abc123", false},
		{"valid single char", "a", false},
		{"invalid uppercase", "INVALID", true},
		{"invalid starts with hyphen", "-invalid", true},
		{"invalid ends with hyphen", "invalid-", true},
		{"invalid too long", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", true}, // 64 chars
		{"invalid underscore", "invalid_name", true},
		{"empty", "", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ValidateDNSName(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateDNSName(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
			}
		})
	}
}

func TestValidateTimeString(t *testing.T) {
	tests := []struct {
		name        string
		input       string
		wantErr     bool
		errContains string
	}{
		{"valid 1h", "1h", false, ""},
		{"valid 1h30m", "1h30m", false, ""},
		{"valid 45m", "45m", false, ""},
		{"invalid format", "abc", true, "invalid format"},
		{"too short", "10m", true, "must be more than 30 mins"},
		{"too long", "360h", true, "must be less than 14 days"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ValidateTimeString(tt.input)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateTimeString(%q) error = %v, wantErr %v", tt.input, err, tt.wantErr)
			}
		})
	}
}
