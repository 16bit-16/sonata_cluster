/*
 * can_test.c - CandleLight (gs_usb) 직접 CAN 전송 테스트
 * libusb로 gs_usb 프로토콜 직접 구현 → 에러 프레임 감지 가능
 *
 * 빌드: make
 * 실행: sudo ./can_test
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>
#include <libusb.h>

/* gs_usb control request codes */
#define GSUSB_BREQ_HOST_FORMAT  0
#define GSUSB_BREQ_BITTIMING    1
#define GSUSB_BREQ_MODE         2

/* channel mode */
#define GS_CAN_MODE_RESET  0
#define GS_CAN_MODE_START  1

/* channel flags */
#define GS_CAN_FLAG_LISTEN_ONLY  0x01
#define GS_CAN_FLAG_LOOPBACK     0x02
#define GS_CAN_FLAG_ONE_SHOT     0x08

/* CAN ID flags */
#define CAN_EFF_FLAG   0x80000000U
#define CAN_RTR_FLAG   0x40000000U
#define CAN_ERR_FLAG   0x20000000U
#define CAN_ERR_BUSOFF 0x00000040U

#pragma pack(push, 1)
typedef struct {
    uint32_t prop_seg;
    uint32_t phase_seg1;
    uint32_t phase_seg2;
    uint32_t sjw;
    uint32_t brp;
} gs_bittiming_t;

typedef struct {
    uint32_t mode;
    uint32_t flags;
} gs_mode_t;

typedef struct {
    uint32_t echo_id;
    uint32_t can_id;
    uint8_t  dlc;
    uint8_t  channel;
    uint8_t  flags;
    uint8_t  pad;
    uint8_t  data[8];
} gs_frame_t;  /* 20 bytes */
#pragma pack(pop)

/*
 * 500kbps @ 48MHz APB (STM32F072 UCAN):
 * brp=6 → tq_clk=8MHz, total TQ=16 → 8MHz/16=500kbps
 * sample point = (1+prop+ps1)/16 = 14/16 = 87.5%
 * 주의: {1,13,2,1,6}은 17TQ=470.6kbps (틀린값)
 */
static gs_bittiming_t bt500k = {2, 11, 2, 1, 6};

static volatile int running = 1;
void sig_handler(int s) { (void)s; running = 0; }

int main(void) {
    libusb_context *ctx = NULL;
    libusb_device_handle *dev = NULL;
    uint8_t ep_in = 0, ep_out = 0;
    int r;

    signal(SIGINT, sig_handler);
    libusb_init(&ctx);

    /* 알려진 CandleLight VID:PID 시도 */
    struct { uint16_t vid, pid; } devlist[] = {
        {0x1D50, 0x606F},  /* CandleLight / FYSETC UCAN */
        {0x1D50, 0x5741},  /* 일부 변형 */
        {0x1209, 0x2323},  /* 클론 */
        {0, 0}
    };

    for (int i = 0; devlist[i].vid && !dev; i++) {
        dev = libusb_open_device_with_vid_pid(ctx, devlist[i].vid, devlist[i].pid);
        if (dev)
            printf("디바이스 발견: 0x%04X:0x%04X\n", devlist[i].vid, devlist[i].pid);
    }

    if (!dev) {
        printf("CandleLight 디바이스 없음. sudo로 실행했나요?\n");
        /* 연결된 USB 장치 목록 출력 */
        libusb_device **list;
        ssize_t cnt = libusb_get_device_list(ctx, &list);
        printf("연결된 USB 장치 (VID:PID):\n");
        for (ssize_t i = 0; i < cnt; i++) {
            struct libusb_device_descriptor desc;
            if (libusb_get_device_descriptor(list[i], &desc) == 0)
                printf("  0x%04X:0x%04X\n", desc.idVendor, desc.idProduct);
        }
        libusb_free_device_list(list, 1);
        libusb_exit(ctx);
        return 1;
    }

    /* 커널 드라이버 분리 후 인터페이스 클레임 */
    libusb_detach_kernel_driver(dev, 0);
    r = libusb_claim_interface(dev, 0);
    if (r < 0) {
        printf("인터페이스 클레임 실패: %s\n", libusb_error_name(r));
        libusb_close(dev);
        libusb_exit(ctx);
        return 1;
    }

    /* 엔드포인트 자동 감지 */
    libusb_device *device = libusb_get_device(dev);
    struct libusb_config_descriptor *config;
    libusb_get_active_config_descriptor(device, &config);
    const struct libusb_interface_descriptor *idesc = &config->interface[0].altsetting[0];
    for (int i = 0; i < idesc->bNumEndpoints; i++) {
        const struct libusb_endpoint_descriptor *ep = &idesc->endpoint[i];
        if ((ep->bmAttributes & 3) == LIBUSB_TRANSFER_TYPE_BULK) {
            if (ep->bEndpointAddress & 0x80) ep_in  = ep->bEndpointAddress;
            else                              ep_out = ep->bEndpointAddress;
        }
    }
    libusb_free_config_descriptor(config);
    printf("엔드포인트: IN=0x%02X  OUT=0x%02X\n", ep_in, ep_out);

    /* host format (little-endian) */
    uint32_t fmt = 0;
    libusb_control_transfer(dev,
        LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_INTERFACE,
        GSUSB_BREQ_HOST_FORMAT, 1, 0, (uint8_t*)&fmt, 4, 1000);

    /* bittiming 500kbps */
    r = libusb_control_transfer(dev,
        LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_INTERFACE,
        GSUSB_BREQ_BITTIMING, 0, 0, (uint8_t*)&bt500k, sizeof(bt500k), 1000);
    printf("bittiming 설정: %s\n", r >= 0 ? "OK" : libusb_error_name(r));

    /* 채널 시작 (재전송 허용 - 클러스터가 ACK 하면 정상 전달됨) */
    gs_mode_t mode = {GS_CAN_MODE_START, 0};
    r = libusb_control_transfer(dev,
        LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_INTERFACE,
        GSUSB_BREQ_MODE, 0, 0, (uint8_t*)&mode, sizeof(mode), 1000);
    printf("채널 시작: %s\n", r >= 0 ? "OK" : libusb_error_name(r));

    /* ── 수신 테스트: 클러스터에서 오는 신호 확인 (2초) ── */
    printf("\n[1단계] 수신 대기 2초 (클러스터 자체 메시지 확인)...\n");
    {
        struct timespec ts0, tsn;
        clock_gettime(CLOCK_MONOTONIC, &ts0);
        int rx_count = 0;
        while (1) {
            clock_gettime(CLOCK_MONOTONIC, &tsn);
            double e = (tsn.tv_sec - ts0.tv_sec) + (tsn.tv_nsec - ts0.tv_nsec) * 1e-9;
            if (e >= 2.0) break;
            gs_frame_t rf;
            memset(&rf, 0, sizeof(rf));
            int rxf = 0;
            int rr = libusb_bulk_transfer(dev, ep_in, (uint8_t*)&rf, sizeof(rf)+4, &rxf, 50);
            if (rr == 0 && rxf >= (int)sizeof(gs_frame_t)) {
                if (!(rf.can_id & CAN_ERR_FLAG)) {
                    printf("  RX: ID=0x%03X dlc=%d data=%02X %02X %02X %02X %02X %02X %02X %02X\n",
                        rf.can_id, rf.dlc,
                        rf.data[0], rf.data[1], rf.data[2], rf.data[3],
                        rf.data[4], rf.data[5], rf.data[6], rf.data[7]);
                    rx_count++;
                }
            }
        }
        printf("  수신된 메시지: %d개\n", rx_count);
    }

    /* ── RPM sweep 테스트: 각 값 3초씩, byte[1]과 byte[3] 동시 변경 ── */
    /* byte[1]=ctr (rolling counter), byte[3]=RPM/40 고정
     * 4800 RPM 원인 분석: byte[1]=counter가 순환하면서 4800이 나왔을 가능성 확인 */
    struct {
        uint8_t b1;  /* byte[1] */
        uint8_t b3;  /* byte[3] = RPM/40 */
        const char *label;
    } rpm_steps[] = {
        {0x00, 20,  "800 RPM  (b1=0x00, b3=0x14)"},
        {0x00, 50,  "2000 RPM (b1=0x00, b3=0x32)"},
        {0x00, 75,  "3000 RPM (b1=0x00, b3=0x4B)"},
        {0x00, 100, "4000 RPM (b1=0x00, b3=0x64)"},
        {0x00, 20,  "800 RPM  (b1=0x00, b3=0x14) 복귀"},
    };
    int nsteps = (int)(sizeof(rpm_steps)/sizeof(rpm_steps[0]));

    printf("\n[2단계] RPM sweep 테스트 (각 3초씩)...\n");
    int sent = 0, errors = 0, busoff = 0;
    uint8_t counter = 0;

    for (int step = 0; step < nsteps && running; step++) {
        printf("  → %s\n", rpm_steps[step].label);
        struct timespec ts_start, ts_now;
        clock_gettime(CLOCK_MONOTONIC, &ts_start);

        while (running) {
            clock_gettime(CLOCK_MONOTONIC, &ts_now);
            double elapsed = (ts_now.tv_sec - ts_start.tv_sec)
                           + (ts_now.tv_nsec - ts_start.tv_nsec) * 1e-9;
            if (elapsed >= 3.0) break;

        /* TX 프레임 구성 */
        gs_frame_t frame;
        memset(&frame, 0, sizeof(frame));
        frame.echo_id  = sent;
        frame.can_id   = 0x316;
        frame.dlc      = 8;
        frame.channel  = 0;
        frame.data[0]  = 0x01;
        frame.data[1]  = rpm_steps[step].b1;
        frame.data[2]  = 0xFF;
        frame.data[3]  = rpm_steps[step].b3;
        frame.data[4]  = counter;   /* rolling counter only in byte[4] */
        frame.data[5]  = 0x15;
        frame.data[6]  = 0x00;
        frame.data[7]  = 0x70;

        int xf = 0;
        r = libusb_bulk_transfer(dev, ep_out,
            (uint8_t*)&frame, sizeof(frame), &xf, 200);
        if (r < 0) {
            printf("TX 오류: %s\n", libusb_error_name(r));
            errors++;
        } else {
            sent++;
        }

        /* RX로 에러 프레임 수신 (1ms 타임아웃) */
        gs_frame_t rxframe;
        memset(&rxframe, 0, sizeof(rxframe));
        int rxf = 0;
        r = libusb_bulk_transfer(dev, ep_in,
            (uint8_t*)&rxframe, sizeof(rxframe) + 4, &rxf, 1);
        if (r == 0 && rxf >= (int)sizeof(gs_frame_t)) {
            if (rxframe.can_id & CAN_ERR_FLAG) {
                if (rxframe.can_id & CAN_ERR_BUSOFF) {
                    busoff++;
                    printf("!!! BUS-OFF 에러 (frame #%d) !!!\n", sent);
                } else {
                    printf("CAN 에러 프레임: ID=0x%08X data=%02X %02X\n",
                        rxframe.can_id, rxframe.data[0], rxframe.data[1]);
                }
            }
        }

        /* 진행 상황 출력 */
        if (sent % 100 == 0 && sent > 0)
            printf("  %.1f초: %d프레임 전송, 오류=%d, busoff=%d\n",
                elapsed, sent, errors, busoff);

        counter++;
        usleep(10000);  /* 10ms = 100Hz */
        } /* while (running) */
    } /* for (step) */

    printf("\n결과: 전송=%d, TX오류=%d, BUS-OFF=%d\n", sent, errors, busoff);

    /* 채널 정지 */
    mode.mode = GS_CAN_MODE_RESET;
    libusb_control_transfer(dev,
        LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_INTERFACE,
        GSUSB_BREQ_MODE, 0, 0, (uint8_t*)&mode, sizeof(mode), 1000);

    libusb_release_interface(dev, 0);
    libusb_close(dev);
    libusb_exit(ctx);
    return 0;
}
