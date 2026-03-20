/**
 * ets2_bridge.cpp
 * ETS2 SCS SDK 플러그인 - 텔레메트리 데이터를 Unix Socket으로 전송.
 *
 * 빌드:  make
 * 설치:  make install
 *        ~/Library/Application Support/Steam/steamapps/common/
 *        Euro Truck Simulator 2/plugins/ets2_bridge.dylib
 */

#include "sdk/scssdk_telemetry.h"
#include "sdk/scssdk_value.h"
#include "sdk/scssdk_telemetry_event.h"
#include "sdk/scssdk_telemetry_channel.h"
#include "sdk/eurotrucks2/scssdk_eut2.h"
#include "sdk/eurotrucks2/scssdk_telemetry_eut2.h"
#include "sdk/common/scssdk_telemetry_common_configs.h"
#include "sdk/common/scssdk_telemetry_common_channels.h"
#include "sdk/common/scssdk_telemetry_truck_common_channels.h"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <cstring>
#include <cstdio>
#include <cmath>
#include <atomic>
#include <string>
#include <sstream>
#include <iomanip>

#define SOCKET_PATH "/tmp/ets2_telemetry.sock"

// ── 텔레메트리 상태 (게임 스레드에서 갱신) ─────────────────────────────────

struct TelemetryState {
    float   speed_ms      = 0.f;
    float   rpm           = 0.f;
    float   fuel          = 0.f;
    float   fuel_capacity = 700.f;  // 기본값 700L (트럭 평균)
    int32_t gear          = 0;
    bool    engine_on     = false;
    bool    parking_brake = false;
    float   coolant_temp  = 20.f;
    float   odometer      = 0.f;
};

static TelemetryState g_state;
static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;

// ── 소켓 서버 스레드 ────────────────────────────────────────────────────────

static std::atomic<bool> g_running{false};
static pthread_t         g_thread;
static int               g_server_fd = -1;
static int               g_client_fd = -1;

static std::string build_json(const TelemetryState &s) {
    std::ostringstream o;
    o << std::fixed << std::setprecision(4);
    o << "{"
      << "\"speed\":"           << s.speed_ms      << ","
      << "\"engineRpm\":"       << s.rpm            << ","
      << "\"fuel\":"            << s.fuel           << ","
      << "\"fuelCapacity\":"    << s.fuel_capacity  << ","
      << "\"gear\":"            << s.gear           << ","
      << "\"engineEnabled\":"   << (s.engine_on     ? "true" : "false") << ","
      << "\"parkBrake\":"       << (s.parking_brake ? "true" : "false") << ","
      << "\"waterTemperature\":" << s.coolant_temp  << ","
      << "\"odometer\":"        << s.odometer
      << "}\n";
    return o.str();
}

static void* socket_thread(void*) {
    // 소켓 파일 잔여물 제거
    unlink(SOCKET_PATH);

    g_server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (g_server_fd < 0) {
        fprintf(stderr, "[ets2_bridge] socket() failed\n");
        return nullptr;
    }

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);

    if (bind(g_server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "[ets2_bridge] bind() failed\n");
        close(g_server_fd);
        return nullptr;
    }

    listen(g_server_fd, 1);
    fprintf(stderr, "[ets2_bridge] Listening on %s\n", SOCKET_PATH);

    while (g_running.load()) {
        // accept는 non-blocking 처리 (1초 타임아웃)
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(g_server_fd, &fds);
        struct timeval tv{1, 0};

        if (select(g_server_fd + 1, &fds, nullptr, nullptr, &tv) <= 0) {
            continue;
        }

        g_client_fd = accept(g_server_fd, nullptr, nullptr);
        if (g_client_fd < 0) continue;

        fprintf(stderr, "[ets2_bridge] Client connected\n");

        // 연결된 동안 20Hz로 JSON 전송
        while (g_running.load()) {
            TelemetryState snapshot;
            pthread_mutex_lock(&g_mutex);
            snapshot = g_state;
            pthread_mutex_unlock(&g_mutex);

            std::string json = build_json(snapshot);
            ssize_t sent = send(g_client_fd, json.c_str(), json.size(), MSG_NOSIGNAL);
            if (sent < 0) {
                fprintf(stderr, "[ets2_bridge] Client disconnected\n");
                break;
            }

            usleep(50000); // 50ms = 20Hz
        }

        close(g_client_fd);
        g_client_fd = -1;
    }

    close(g_server_fd);
    g_server_fd = -1;
    unlink(SOCKET_PATH);
    return nullptr;
}

// ── SCS SDK 채널 콜백 ───────────────────────────────────────────────────────

SCSAPI_VOID cb_speed(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_float) return;
    pthread_mutex_lock(&g_mutex);
    g_state.speed_ms = val->value_float.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_rpm(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_float) return;
    pthread_mutex_lock(&g_mutex);
    g_state.rpm = val->value_float.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_fuel(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_float) return;
    pthread_mutex_lock(&g_mutex);
    g_state.fuel = val->value_float.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_gear(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_s32) return;
    pthread_mutex_lock(&g_mutex);
    g_state.gear = val->value_s32.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_engine_on(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_bool) return;
    pthread_mutex_lock(&g_mutex);
    g_state.engine_on = val->value_bool.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_parking_brake(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_bool) return;
    pthread_mutex_lock(&g_mutex);
    g_state.parking_brake = val->value_bool.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_coolant(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_float) return;
    pthread_mutex_lock(&g_mutex);
    g_state.coolant_temp = val->value_float.value;
    pthread_mutex_unlock(&g_mutex);
}

SCSAPI_VOID cb_odometer(const scs_string_t, const scs_u32_t, const scs_value_t *val, const scs_context_t) {
    if (!val || val->type != SCS_VALUE_TYPE_float) return;
    pthread_mutex_lock(&g_mutex);
    g_state.odometer = val->value_float.value;
    pthread_mutex_unlock(&g_mutex);
}

// ── 플러그인 진입점 ─────────────────────────────────────────────────────────

SCSAPI_RESULT scs_telemetry_init(const scs_u32_t version, const scs_telemetry_init_params_t *const params) {
    if (version != SCS_TELEMETRY_VERSION_1_00) {
        return SCS_RESULT_unsupported;
    }

    const scs_telemetry_init_params_v100_t *p =
        static_cast<const scs_telemetry_init_params_v100_t*>(params);

    auto &reg = p->register_for_channel;

#define REG(name, cb, type) \
    reg(name, SCS_U32_NIL, type, SCS_TELEMETRY_CHANNEL_FLAG_none, cb, nullptr)

    REG(SCS_TELEMETRY_TRUCK_CHANNEL_speed,             cb_speed,         SCS_VALUE_TYPE_float);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_engine_rpm,        cb_rpm,           SCS_VALUE_TYPE_float);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_fuel,              cb_fuel,          SCS_VALUE_TYPE_float);
    // fuel_capacity는 채널이 아닌 config로 제공됨 - 트럭마다 다름 (기본 700L 가정)
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_displayed_gear,    cb_gear,          SCS_VALUE_TYPE_s32);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_engine_enabled,    cb_engine_on,     SCS_VALUE_TYPE_bool);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_parking_brake,     cb_parking_brake, SCS_VALUE_TYPE_bool);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_water_temperature, cb_coolant,       SCS_VALUE_TYPE_float);
    REG(SCS_TELEMETRY_TRUCK_CHANNEL_odometer,          cb_odometer,      SCS_VALUE_TYPE_float);

#undef REG

    // 소켓 서버 스레드 시작
    g_running.store(true);
    pthread_create(&g_thread, nullptr, socket_thread, nullptr);

    fprintf(stderr, "[ets2_bridge] Plugin initialized\n");
    return SCS_RESULT_ok;
}

SCSAPI_VOID scs_telemetry_shutdown() {
    g_running.store(false);
    if (g_client_fd >= 0) { close(g_client_fd); g_client_fd = -1; }
    if (g_server_fd >= 0) { close(g_server_fd); g_server_fd = -1; }
    pthread_join(g_thread, nullptr);
    unlink(SOCKET_PATH);
    fprintf(stderr, "[ets2_bridge] Plugin shutdown\n");
}
