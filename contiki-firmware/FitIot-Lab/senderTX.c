/*
 * sender.c – adaptive TX power phases
 * Automatically cycles through 4 TX power phases at runtime:
 *   Phase 0  STABLE    0 dBm   (0–PHASE_DURATION_S s)
 *   Phase 1  DEGRADED  -9 dBm  (PHASE_DURATION_S–2×PHASE_DURATION_S s)
 *   Phase 2  RECOVERY  -5 dBm  (2×PHASE_DURATION_S–3×PHASE_DURATION_S s)
 *   Phase 3  CRITICAL  -17 dBm (3×PHASE_DURATION_S–end s)
 *
 * Fresh power-on  → prints "PHASE 0 STABLE tx_reg=0xXX"
 * Watchdog reboot → prints "REBOOT phase=N LABEL tx_reg=0xXX"  (no PHASE 0)
 * Each transition → prints "PHASE N LABEL tx_reg=0xXX"
 */

#include "contiki.h"
#include "lib/random.h"
#include "sys/ctimer.h"
#include "sys/etimer.h"
#include "net/ip/uip.h"
#include "net/ipv6/uip-ds6.h"
#include "net/ip/uip-debug.h"
#include "sys/node-id.h"
#include "simple-udp.h"
#include "servreg-hack.h"
#include "rf2xx.h"
#include "rf2xx/rf2xx_regs.h"

/* STM32F103 backup registers – raw MMIO, no StdPeriph headers required.
 * These registers survive a watchdog reset but are cleared on power-cycle
 * (VBAT tied to VDD on iotlab-m3), which is exactly the granularity we need. */
#include <stdint.h>
#define _STM32_RCC_APB1ENR  (*(volatile uint32_t *)0x4002101Cu)
#define _STM32_PWR_CR       (*(volatile uint32_t *)0x40007000u)
#define _STM32_BKP_DR1      (*(volatile uint16_t *)0x40006C04u)
#define _STM32_BKP_DR2      (*(volatile uint16_t *)0x40006C08u)

#include <stdio.h>
#include <string.h>

extern rf2xx_t rf231;

/*---------------------------------------------------------------------------*/
/* Experiment parameters – controlled from Makefile                          */
/*---------------------------------------------------------------------------*/

#define UDP_PORT        1234
#define SERVICE_ID      190

#ifndef NB_PACKETS
#define NB_PACKETS      15
#endif

#ifndef SEND_BUFFER_SIZE
#define SEND_BUFFER_SIZE 8
#endif

#ifndef NB_SECONDS
#define NB_SECONDS      1
#endif

#ifndef PHASE_DURATION_S
#define PHASE_DURATION_S 900    /* 15 min per phase */
#endif

#define SEND_INTERVAL   (NB_SECONDS * CLOCK_SECOND)
#define NB_PHASES       4

/*---------------------------------------------------------------------------*/
/* TX power register values – one per phase                                  */
/*---------------------------------------------------------------------------*/
static const uint8_t phase_tx_reg[NB_PHASES] = {
    RF2XX_PHY_TX_PWR_DEFAULT__PA_BUF_LT | RF2XX_PHY_TX_PWR_TX_PWR_VALUE__0dBm,
    RF2XX_PHY_TX_PWR_DEFAULT__PA_BUF_LT | RF2XX_PHY_TX_PWR_TX_PWR_VALUE__m9dBm,
    RF2XX_PHY_TX_PWR_DEFAULT__PA_BUF_LT | RF2XX_PHY_TX_PWR_TX_PWR_VALUE__m5dBm,
    RF2XX_PHY_TX_PWR_DEFAULT__PA_BUF_LT | RF2XX_PHY_TX_PWR_TX_PWR_VALUE__m17dBm,
};

static const char *phase_labels[NB_PHASES] = {
    "STABLE", "DEGRADED", "RECOVERY", "CRITICAL"
};

/*---------------------------------------------------------------------------*/
/* Backup-register helpers                                                   */
/* DR1 holds a magic sentinel; DR2 holds the last known phase index.        */
/*---------------------------------------------------------------------------*/
#define BKP_MAGIC  0xA5A5u

static void bkp_init(void)
{
    _STM32_RCC_APB1ENR |= (1u << 28) | (1u << 27); /* enable PWR + BKP clocks */
    _STM32_PWR_CR      |= (1u << 8);               /* DBP: unlock backup domain */
}

/* Returns saved phase (0–NB_PHASES-1) on watchdog reboot, 0xFF on fresh boot. */
static uint8_t bkp_load(void)
{
    if(_STM32_BKP_DR1 == (uint16_t)BKP_MAGIC) {
        uint16_t p = _STM32_BKP_DR2;
        if(p < NB_PHASES) return (uint8_t)p;
    }
    return 0xFF;
}

static void bkp_save(uint8_t phase)
{
    _STM32_BKP_DR1 = (uint16_t)BKP_MAGIC;
    _STM32_BKP_DR2 = (uint16_t)phase;
}

/*---------------------------------------------------------------------------*/
static struct simple_udp_connection unicast_connection;
static uint32_t cpt = 0;
static uip_ipaddr_t id;

/*---------------------------------------------------------------------------*/
PROCESS(unicast_sender_process, "Unicast sender process");
AUTOSTART_PROCESSES(&unicast_sender_process);
/*---------------------------------------------------------------------------*/

static void
receiver(struct simple_udp_connection *c,
         const uip_ipaddr_t *sender_addr,
         uint16_t sender_port,
         const uip_ipaddr_t *receiver_addr,
         uint16_t receiver_port,
         const uint8_t *data,
         uint16_t datalen)
{
    /* not used on sender side */
}

/*---------------------------------------------------------------------------*/
static void
set_global_address(void)
{
    uip_ipaddr_t ipaddr;
    int i;
    uint8_t state;

    uip_ip6addr(&ipaddr, UIP_DS6_DEFAULT_PREFIX, 0, 0, 0, 0, 0, 0, 0);
    uip_ds6_set_addr_iid(&ipaddr, &uip_lladdr);
    uip_ds6_addr_add(&ipaddr, 0, ADDR_AUTOCONF);

    printf("IPv6 addresses: ");
    for(i = 0; i < UIP_DS6_ADDR_NB; i++) {
        state = uip_ds6_if.addr_list[i].state;
        if(uip_ds6_if.addr_list[i].isused &&
           (state == ADDR_TENTATIVE || state == ADDR_PREFERRED)) {
            uip_debug_ipaddr_print(&uip_ds6_if.addr_list[i].ipaddr);
            id = uip_ds6_if.addr_list[i].ipaddr;
            printf("\n");
        }
    }
}

/*---------------------------------------------------------------------------*/
PROCESS_THREAD(unicast_sender_process, ev, data)
{
    static struct etimer send_timer;
    static struct etimer phase_timer;
    static uint8_t current_phase;
    uip_ipaddr_t *addr;
    int i;

    PROCESS_BEGIN();

    servreg_hack_init();
    set_global_address();
    simple_udp_register(&unicast_connection, UDP_PORT, NULL, UDP_PORT, receiver);

    /* ── Boot vs reboot detection ─────────────────────────────────────────── */
    bkp_init();
    {
        uint8_t saved = bkp_load();
        if(saved == 0xFF) {
            /* Fresh power-on: start at phase 0 */
            current_phase = 0;
            bkp_save(0);
            rf2xx_reg_write(rf231, RF2XX_REG__PHY_TX_PWR, phase_tx_reg[0]);
            printf("PHASE 0 %s tx_reg=0x%02x\n", phase_labels[0], phase_tx_reg[0]);
        } else {
            /* Watchdog reboot: restore last known phase – no PHASE 0 printed */
            current_phase = saved;
            rf2xx_reg_write(rf231, RF2XX_REG__PHY_TX_PWR, phase_tx_reg[current_phase]);
            printf("REBOOT phase=%u %s tx_reg=0x%02x\n",
                   current_phase, phase_labels[current_phase],
                   phase_tx_reg[current_phase]);
        }
    }

    etimer_set(&send_timer,  SEND_INTERVAL);
    etimer_set(&phase_timer, (clock_time_t)PHASE_DURATION_S * CLOCK_SECOND);

    while(1) {
        PROCESS_WAIT_EVENT();

        /* ── Phase change timer ───────────────────────────────────────────── */
        /*
         * Guard: once current_phase reaches NB_PHASES the timer is left
         * expired on purpose.  Without the guard, every send-timer wake-up
         * would re-enter this block and silently increment current_phase
         * until uint8_t wraps to 0, reprinting "PHASE 0" ~17 s after the
         * last phase expires.
         */
        if(etimer_expired(&phase_timer) && current_phase < NB_PHASES) {
            current_phase++;
            if(current_phase < NB_PHASES) {
                rf2xx_reg_write(rf231, RF2XX_REG__PHY_TX_PWR,
                                phase_tx_reg[current_phase]);
                printf("PHASE %u %s tx_reg=0x%02x\n",
                       current_phase,
                       phase_labels[current_phase],
                       phase_tx_reg[current_phase]);
                bkp_save(current_phase);
                /* Only reset the timer if there is still a next phase */
                if(current_phase + 1 < NB_PHASES)
                    etimer_reset(&phase_timer);
            }
            /* current_phase == NB_PHASES: all phases done.
               Timer is left expired; guard above blocks all future re-entries. */
        }

        /* ── Send timer ──────────────────────────────────────────────────── */
        if(etimer_expired(&send_timer)) {
            addr = servreg_hack_lookup(SERVICE_ID);

            if(addr != NULL) {
                for(i = 0; i < NB_PACKETS; i++) {
                    char buf[SEND_BUFFER_SIZE + 1];
                    snprintf(buf, sizeof(buf), "%08lu", (unsigned long)cpt);
                    cpt++;

                    printf("s ");
                    uip_debug_ipaddr_print(&id);
                    printf(" %s\n", buf);

                    simple_udp_sendto(&unicast_connection, buf, SEND_BUFFER_SIZE, addr);
                }
            } else {
                printf("Service %d not found\n", SERVICE_ID);
            }

            etimer_reset(&send_timer);
        }
    }

    PROCESS_END();
}
/*---------------------------------------------------------------------------*/
