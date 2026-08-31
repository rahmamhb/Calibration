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

/* Updated RPL include for Contiki-NG */
#include "net/routing/routing.h"    /* was: net/rpl/rpl.h */

/* NO servreg-hack in Contiki-NG! Removed: #include "servreg-hack.h" */
#include "net/netstack.h"
#include "net/packetbuf.h"
#include "csma-runtime.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
/* ===================== CONFIGURATION ===================== */
#define UDP_PORT 1234
/* SERVICE_ID removed - no servreg-hack in Contiki-NG */

/* ===================== UDP CONNECTION ===================== */
static struct simple_udp_connection unicast_connection;

/*---------------------------------------------------------------------------*/
PROCESS(unicast_receiver_process, "Unicast receiver process (Contiki-NG)");
AUTOSTART_PROCESSES(&unicast_receiver_process);
/*---------------------------------------------------------------------------*/

/* UDP receive callback - called when a packet arrives */
static void
udp_rx_callback(struct simple_udp_connection *c,
                const uip_ipaddr_t *sender_addr,
                uint16_t sender_port,
                const uip_ipaddr_t *receiver_addr,
                uint16_t receiver_port,
                const uint8_t *data,
                uint16_t datalen)
{
  /* Log: "r <sender_ipv6> <packet_content> <length>"
   * Same format as FIT IoT-LAB output for comparison */
  printf("r ");
  uip_debug_ipaddr_print(sender_addr);
  printf(" %s %d\n", (char *)data, datalen);
}

/*---------------------------------------------------------------------------*/
/* Print all IPv6 addresses of this node */
static void
print_addresses(void)
{
  int i;
  uint8_t state;

  printf("IPv6 addresses:\n");
  for(i = 0; i < UIP_DS6_ADDR_NB; i++) {
    state = uip_ds6_if.addr_list[i].state;
    if(uip_ds6_if.addr_list[i].isused &&
       (state == ADDR_TENTATIVE || state == ADDR_PREFERRED)) {
      printf("  ");
      uip_debug_ipaddr_print(&uip_ds6_if.addr_list[i].ipaddr);
      printf("\n");
    }
  }
}

/*---------------------------------------------------------------------------*/
/* Set up this node as RPL root (DAG coordinator)
 * In Contiki-NG, we use NETSTACK_ROUTING instead of direct rpl_* calls */
static void
create_rpl_dag(void)
{
  /* Check if routing protocol supports root mode */
  if(NETSTACK_ROUTING.node_is_root()) {
    printf("Already RPL root\n");
    return;
  }

  /* Set this node as the RPL root
   * This replaces: rpl_set_root() + rpl_get_any_dag() + rpl_set_prefix() */
  NETSTACK_ROUTING.root_set_prefix(NULL, NULL);  /* Use default prefix */
  NETSTACK_ROUTING.root_start();                  /* Start as root */

  printf("Created RPL DAG - this node is root\n");
}

/*---------------------------------------------------------------------------*/
PROCESS_THREAD(unicast_receiver_process, ev, data)
{
  PROCESS_BEGIN();

  /* Print our IPv6 addresses so senders can see our address in logs
   * IMPORTANT: Note the fd00:: address - this is what senders use! */
  print_addresses();

  /* Set up as RPL root
   * Replaces: servreg_hack_init() + servreg_hack_register()
   * In Contiki-NG, RPL handles routing automatically once root is set */
  create_rpl_dag();

  /* Register UDP connection to listen for incoming packets */
  simple_udp_register(&unicast_connection, UDP_PORT,
                      NULL, UDP_PORT, udp_rx_callback);

  printf("Receiver ready on UDP port %d\n", UDP_PORT);
  printf("Waiting for packets...\n");

  /* Main loop - just wait for events (UDP callbacks handle everything) */
  while(1) {
    PROCESS_WAIT_EVENT();
  }

  PROCESS_END();
}
/*---------------------------------------------------------------------------*/
