/*
 * Copyright (c) 2011, Swedish Institute of Computer Science.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of the Institute nor the names of its contributors
 *    may be used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE INSTITUTE AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE INSTITUTE OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * This file is part of the Contiki-NG operating system.
 * Adapted for Contiki-NG from original Contiki version (TER experiment)
 */

/* ===================== CONTIKI-NG INCLUDES ===================== */
#include "contiki.h"
#include "lib/random.h"
#include "sys/ctimer.h"
#include "sys/etimer.h"

/* Updated IP includes for Contiki-NG */
#include "net/ipv6/uip.h"           /* was: net/ip/uip.h */
#include "net/ipv6/uip-ds6.h"       /* same path */
#include "net/ipv6/uip-debug.h"     /* was: net/ip/uip-debug.h */

/* Updated simple-udp include for Contiki-NG */
#include "net/ipv6/simple-udp.h"  /* was: simple-udp.h */

/* node-id still available in Contiki-NG */
#include "sys/node-id.h"
#include "csma-runtime.h"
/* NO servreg-hack in Contiki-NG! Removed: #include "servreg-hack.h" */

#include <stdio.h>
#include <string.h>

/* ===================== CONFIGURATION ===================== */

#define UDP_PORT 1234

/* Packet counter */
uint32_t cpt2 = 0;

/* Store our own IPv6 address for logging */
uip_ipaddr_t id;

/* ----- TER -----*/

/* Define which CSMA/CA parameter set to use.
 * Uncomment ONE of the following: */
#define CONTIKI_PARAM
/* #define IEEE_PARAM   */
/* #define CUSTOM_PARAM */

/* IEEE 802.15.4 default parameters */
#ifdef IEEE_PARAM
#define CSMA_CONF_MIN_BE        3
#define CSMA_CONF_MAX_BE        5
#define CSMA_CONF_MAX_BACKOFF   4
#endif

/* Contiki default parameters */
#ifdef CONTIKI_PARAM
#define CSMA_CONF_MIN_BE        0
#define CSMA_CONF_MAX_BE        4
#define CSMA_CONF_MAX_BACKOFF   5
#endif

/* Custom parameters (for varying macMinBE experiment) */
#ifdef CUSTOM_PARAM
#define CSMA_CONF_MIN_BE        0
#define CSMA_CONF_MAX_BE        10
#define CSMA_CONF_MAX_BACKOFF   5
#endif

#define CSMA_CONF_MAX_FRAME_RETRIES 7

/* Send interval: 0.5 seconds */
#define NB_SECONDS 0.5
#define SEND_INTERVAL (NB_SECONDS * CLOCK_SECOND)

/* ----- TER -----*/

/* ===================== RECEIVER ADDRESS =====================
 * In Contiki-NG with Cooja, we hardcode the receiver address.
 * The receiver (Mote 1) will have address: fd00::201:1:1:1
 * 
 * HOW TO FIND THE CORRECT ADDRESS:
 * 1. Run the simulation with only the receiver first
 * 2. Look at Mote Output for: "IPv6 addresses: fd00::xxxx"
 * 3. Update the address below
 *
 * Default for Cooja Mote 1: fd00::201:1:1:1
 * ============================================================ */
#define RECEIVER_ADDR_1  0xfe80 // when i run the experiment the receiver @ didnt start with 0xfd00
#define RECEIVER_ADDR_2  0x0000
#define RECEIVER_ADDR_3  0x0000
#define RECEIVER_ADDR_4  0x0000
#define RECEIVER_ADDR_5  0x0201
#define RECEIVER_ADDR_6  0x0001
#define RECEIVER_ADDR_7  0x0001
#define RECEIVER_ADDR_8  0x0001

/* ===================== UDP CONNECTION ===================== */
static struct simple_udp_connection unicast_connection;

/*---------------------------------------------------------------------------*/
PROCESS(unicast_sender_process, "Unicast sender process (Contiki-NG)");
AUTOSTART_PROCESSES(&unicast_sender_process);
/*---------------------------------------------------------------------------*/

/* Callback for incoming UDP packets (sender can also receive) */
static void
udp_rx_callback(struct simple_udp_connection *c,
                const uip_ipaddr_t *sender_addr,
                uint16_t sender_port,
                const uip_ipaddr_t *receiver_addr,
                uint16_t receiver_port,
                const uint8_t *data,
                uint16_t datalen)
{
  printf("Data received on port %d from port %d with length %d\n",
         receiver_port, sender_port, datalen);
}

/*---------------------------------------------------------------------------*/
/* Print all IPv6 addresses of this node and store the global one */
static void
set_global_address(void)
{
  int i;
  uint8_t state;

  printf("IPv6 addresses: ");
  for(i = 0; i < UIP_DS6_ADDR_NB; i++) {
    state = uip_ds6_if.addr_list[i].state;
    if(uip_ds6_if.addr_list[i].isused &&
       (state == ADDR_TENTATIVE || state == ADDR_PREFERRED)) {
      uip_debug_ipaddr_print(&uip_ds6_if.addr_list[i].ipaddr);
      /* Store global address (fd00::) for logging in printf("s ...") */
      if(uip_ds6_if.addr_list[i].ipaddr.u8[0] == 0xfd) {
        id = uip_ds6_if.addr_list[i].ipaddr;
      }
      printf("\n");
    }
  }
}
/*---------------------------------------------------------------------------*/
PROCESS_THREAD(unicast_sender_process, ev, data)
{
  static struct etimer send_timer;
  static uip_ipaddr_t receiver_addr;
  static uint8_t addr_initialized = 0;

  PROCESS_BEGIN();

  /* Print our IPv6 addresses */
  set_global_address();

  /* Register UDP connection */
  simple_udp_register(&unicast_connection, UDP_PORT,
                      NULL, UDP_PORT, udp_rx_callback);

  /* Initialize receiver address (hardcoded - no servreg-hack needed) */
  if(!addr_initialized) {
    uip_ip6addr(&receiver_addr,
                RECEIVER_ADDR_1, RECEIVER_ADDR_2,
                RECEIVER_ADDR_3, RECEIVER_ADDR_4,
                RECEIVER_ADDR_5, RECEIVER_ADDR_6,
                RECEIVER_ADDR_7, RECEIVER_ADDR_8);
    addr_initialized = 1;
    printf("Receiver address set to: ");
    uip_debug_ipaddr_print(&receiver_addr);
    printf("\n");
  }

  /* Set timer for first send */
  etimer_set(&send_timer, SEND_INTERVAL);

  /* ------- TER: Configure CSMA parameters at runtime -------*/
  set_csma_min_be(CSMA_CONF_MIN_BE);
  set_csma_max_be(CSMA_CONF_MAX_BE);
  set_csma_max_backoff(CSMA_CONF_MAX_BACKOFF);
  set_csma_max_frame_retries(CSMA_CONF_MAX_FRAME_RETRIES);
  printf("CSMA params: minBE=%d maxBE=%d maxBackoff=%d maxRetries=%d\n",
         CSMA_CONF_MIN_BE, CSMA_CONF_MAX_BE,
         CSMA_CONF_MAX_BACKOFF, CSMA_CONF_MAX_FRAME_RETRIES);
  /* ------- TER -------*/

  while(1) {
    PROCESS_WAIT_EVENT();

    if(etimer_expired(&send_timer)) {

      /* Build packet: 7-digit zero-padded counter */
      char buf[20];
      snprintf(buf, sizeof(buf), "%07lu", (unsigned long)cpt2);
      cpt2++;

      /* Log: "s <our_ipv6> <packet_id>" - same format as FIT IoT-LAB */
      printf("s ");
      uip_debug_ipaddr_print(&id);
      printf(" %s\n", buf);

      /* Send UDP packet directly to receiver (no servreg-hack needed) */
      simple_udp_sendto(&unicast_connection, buf, strlen(buf) + 1, &receiver_addr);

      /* Reset timer for next send */
      etimer_reset(&send_timer);
    }
  }

  PROCESS_END();
}
/*---------------------------------------------------------------------------*/
