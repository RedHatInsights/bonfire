package ephemeral

import "os"

// Settings holds configuration for the ephemeral reservation lifecycle.
// Matches bonfire_lib/config.py Settings dataclass.
type Settings struct {
	DefaultNamespacePool        string
	DefaultReservationDuration  string
	DefaultRequester            string
	EphemeralEnvName            string
	DefaultBaseNamespace        string
	IsBot                       bool
}

// DefaultSettings returns settings with all defaults applied.
func DefaultSettings() Settings {
	return Settings{
		DefaultNamespacePool:       "default",
		DefaultReservationDuration: "1h",
		DefaultRequester:           "",
		EphemeralEnvName:           "insights-ephemeral",
		DefaultBaseNamespace:       "ephemeral-base",
		IsBot:                      false,
	}
}

// SettingsFromEnv loads settings from environment variables.
// Matches bonfire_lib/config.py Settings.from_env().
func SettingsFromEnv() Settings {
	s := DefaultSettings()
	if v := os.Getenv("BONFIRE_DEFAULT_NAMESPACE_POOL"); v != "" {
		s.DefaultNamespacePool = v
	}
	if v := os.Getenv("BONFIRE_DEFAULT_DURATION"); v != "" {
		s.DefaultReservationDuration = v
	}
	if v := os.Getenv("BONFIRE_NS_REQUESTER"); v != "" {
		s.DefaultRequester = v
	}
	if v := os.Getenv("EPHEMERAL_ENV_NAME"); v != "" {
		s.EphemeralEnvName = v
	}
	if v := os.Getenv("DEFAULT_BASE_NAMESPACE"); v != "" {
		s.DefaultBaseNamespace = v
	}
	if v := os.Getenv("BONFIRE_BOT"); v == "true" {
		s.IsBot = true
	}
	return s
}
