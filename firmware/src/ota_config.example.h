#pragma once
// Copy to ota_config.h, or retain your existing ota_config.h unchanged.
// Initial network is optional: the captive portal can set it later.
constexpr char OTA_WIFI_SSID[] = "";
constexpr char OTA_WIFI_PASSWORD[] = "";
// Use your existing 16-character alphanumeric OTA token.
// The browser uses this same key to access samples.
constexpr char OTA_TOKEN[] = "ChangeMe12345678";
