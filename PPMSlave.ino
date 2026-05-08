// PPMSlave — ESP32-C3 Mini
// Reads 9-byte big-endian packets from USB serial (">ffB": axis0, axis1, flag)
// and outputs an 8-channel CPPM signal on PPM_PIN for EdgeTX DSC trainer port.

#include "esp_timer.h"
#include <string.h>

// ── Config ────────────────────────────────────────────────────────────────────
#define PPM_PIN           4      // GPIO4 — safe on C3 Mini (avoid 6-11, 18-19)
#define PPM_CHANNELS      4      // 3 active + 1 neutral — fits 11ms frame at full throw
#define PPM_FRAME_US      11000  // 11ms — matches DSMX 1F RF rate exactly
#define PPM_PULSE_US      300    // separator HIGH pulse width in µs
#define SERIAL_BAUD       921600 // reduce serial tx time 780µs → 97µs
#define DEBUG_INTERVAL_MS 200    // how often to print debug lines
// ─────────────────────────────────────────────────────────────────────────────

static volatile uint16_t ppm_channels[PPM_CHANNELS];  // updated by loop()
static volatile uint16_t ppm_snapshot[PPM_CHANNELS];  // snapshot taken at frame start by ISR

static volatile uint32_t frame_count  = 0;
static volatile uint32_t packet_count = 0;
static volatile uint32_t last_pkt_us  = 0;

// PPM ISR state
static volatile uint8_t  ppm_phase  = 0;  // 0=sep-HIGH done→go LOW, 1=ch-LOW done→go HIGH, 2=sync done→new frame
static volatile uint8_t  ppm_ch_idx = 0;
static volatile uint32_t ppm_elapsed = 0;

static esp_timer_handle_t ppm_timer;

// Debug copies (written by loop, read by Serial.printf — safe, single-threaded)
static float    dbg_ax0 = 0, dbg_ax1 = 0;
static uint8_t  dbg_flag = 0;
static uint16_t dbg_ppm[PPM_CHANNELS];

// ── PPM ISR ──────────────────────────────────────────────────────────────────
static void IRAM_ATTR ppm_isr(void* arg) {
  switch (ppm_phase) {

    case 0:  // separator LOW just elapsed → drive HIGH (channel gap or sync)
      digitalWrite(PPM_PIN, HIGH);
      if (ppm_ch_idx < PPM_CHANNELS) {
        uint32_t gap = ppm_snapshot[ppm_ch_idx] - PPM_PULSE_US;
        ppm_elapsed += ppm_snapshot[ppm_ch_idx];
        ppm_ch_idx++;
        esp_timer_start_once(ppm_timer, gap);
        ppm_phase = 1;
      } else {
        uint32_t sync = PPM_FRAME_US - PPM_PULSE_US - ppm_elapsed;
        if (sync < 2000) sync = 2000;  // clamp: never let sync collapse
        esp_timer_start_once(ppm_timer, sync);
        ppm_phase = 2;
      }
      break;

    case 1:  // channel HIGH just elapsed → drive LOW (separator)
      digitalWrite(PPM_PIN, LOW);
      esp_timer_start_once(ppm_timer, PPM_PULSE_US);
      ppm_phase = 0;
      break;

    case 2:  // sync HIGH just elapsed → snapshot channels, start new frame
      frame_count++;
      memcpy((void*)ppm_snapshot, (void*)ppm_channels, PPM_CHANNELS * sizeof(uint16_t));
      ppm_ch_idx  = 0;
      ppm_elapsed = 0;
      ppm_phase   = 0;
      digitalWrite(PPM_PIN, LOW);
      esp_timer_start_once(ppm_timer, PPM_PULSE_US);
      break;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
// Reinterpret 4 big-endian bytes as a native float.
static float be_to_float(const uint8_t* b) {
  uint8_t tmp[4] = {b[3], b[2], b[1], b[0]};
  float f;
  memcpy(&f, tmp, 4);
  return f;
}

static inline float clampf(float v, float lo, float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline uint16_t axis_to_ppm(float v) {
  return (uint16_t)(1500.0f + v * 500.0f);
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(400);
  Serial.println("[PPMSlave] ESP32-C3 Mini starting");
  Serial.printf("[PPMSlave] PPM_PIN=%d  FRAME=%uus  PULSE=%uus  CH=%d\n",
                PPM_PIN, PPM_FRAME_US, PPM_PULSE_US, PPM_CHANNELS);

  for (int i = 0; i < PPM_CHANNELS; i++) {
    ppm_channels[i] = 1500;
    ppm_snapshot[i] = 1500;
  }

  pinMode(PPM_PIN, OUTPUT);
  digitalWrite(PPM_PIN, HIGH);  // idle HIGH = negative polarity (EdgeTX default)

  const esp_timer_create_args_t ta = {
    .callback        = ppm_isr,
    .arg             = NULL,
    .dispatch_method = ESP_TIMER_ISR,
    .name            = "ppm",
    .skip_unhandled_events = false
  };
  ESP_ERROR_CHECK(esp_timer_create(&ta, &ppm_timer));

  // Kick off first separator pulse (negative polarity: idle HIGH, pulse LOW)
  digitalWrite(PPM_PIN, LOW);
  esp_timer_start_once(ppm_timer, PPM_PULSE_US);
  ppm_phase = 0;

  Serial.println("[PPMSlave] PPM running — waiting for serial packets");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
static uint8_t  rx_buf[9];
static uint8_t  rx_idx = 0;
static uint32_t last_rx_us   = 0;
static uint32_t last_debug_ms = 0;

void loop() {
  // Inter-packet gap > 2 ms means we're between packets — re-sync the buffer.
  if (rx_idx > 0 && (micros() - last_rx_us) > 2000) {
    rx_idx = 0;
  }

  // Accumulate serial bytes; process when a full 9-byte packet arrives.
  while (Serial.available() > 0) {
    last_rx_us = micros();
    rx_buf[rx_idx++] = (uint8_t)Serial.read();
    if (rx_idx < 9) continue;
    rx_idx = 0;

    float ax0  = clampf(be_to_float(&rx_buf[0]), -1.0f, 1.0f);
    float ax1  = clampf(be_to_float(&rx_buf[4]), -1.0f, 1.0f);
    uint8_t fl = rx_buf[8];

    ppm_channels[0] = axis_to_ppm(ax0);
    ppm_channels[1] = axis_to_ppm(ax1);
    ppm_channels[2] = fl ? 1750 : 1000;
    for (int i = 3; i < PPM_CHANNELS; i++) ppm_channels[i] = 1500;

    packet_count++;
    last_pkt_us = micros();

    dbg_ax0  = ax0;
    dbg_ax1  = ax1;
    dbg_flag = fl;
    memcpy(dbg_ppm, (void*)ppm_channels, sizeof(dbg_ppm));
  }

  // Throttled debug output — does not block PPM ISR.
  uint32_t now_ms = millis();
  if (now_ms - last_debug_ms >= DEBUG_INTERVAL_MS) {
    last_debug_ms = now_ms;

    uint32_t age_ms = (micros() - last_pkt_us) / 1000;

    Serial.printf("[PKT #%lu] ax0=%.3f ax1=%.3f flag=%u\n",
                  (unsigned long)packet_count, dbg_ax0, dbg_ax1, dbg_flag);
    Serial.printf("[PPM] ch1=%u ch2=%u ch3=%u ch4=%u ch5=%u ch6=%u ch7=%u ch8=%u\n",
                  dbg_ppm[0], dbg_ppm[1], dbg_ppm[2], dbg_ppm[3],
                  dbg_ppm[4], dbg_ppm[5], dbg_ppm[6], dbg_ppm[7]);
    Serial.printf("[TIMING] frames=%lu pkts=%lu age=%lums\n",
                  (unsigned long)frame_count, (unsigned long)packet_count, (unsigned long)age_ms);

    if (packet_count > 0 && age_ms > 500) {
      Serial.printf("[WARN] No packet for %lums — PPM holding last values\n",
                    (unsigned long)age_ms);
    }
  }
}
