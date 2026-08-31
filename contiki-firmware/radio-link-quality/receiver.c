/*
 * unicast-receiver.c
 */
#include "contiki.h"
#include "lib/random.h"
#include "sys/ctimer.h"
#include "sys/etimer.h"
#include "net/ipv6/uip.h"           /* was: net/ip/uip.h */
#include "net/ipv6/uip-ds6.h"
#include "net/ipv6/uip-debug.h"     /* was: net/ip/uip-debug.h */
#include "simple-udp.h"
/* NO servreg-hack in Contiki-NG! Removed: #include "servreg-hack.h" */
#include "net/routing/routing.h"    /* was: net/rpl/rpl.h */
#include "net/netstack.h"
#include "net/packetbuf.h"

#include <stdio.h>
#include <string.h>

#define UDP_PORT    1234
/* SERVICE_ID removed - no servreg-hack in Contiki-NG */

static struct simple_udp_connection unicast_connection;
static uint32_t packets_received = 0;

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
  int16_t rssi = (int16_t)packetbuf_attr(PACKETBUF_ATTR_RSSI);
  int16_t lqi  = (int16_t)packetbuf_attr(PACKETBUF_ATTR_LINK_QUALITY);

  packets_received++;

  printf("r ");
  uip_debug_ipaddr_print(sender_addr);
  printf(" %s rssi=%d lqi=%d count=%lu\n",
         (char *)data,
         rssi,
         lqi,
         packets_received);
}
/*---------------------------------------------------------------------------*/
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
static void
create_rpl_dag(void)
{

  if(NETSTACK_ROUTING.node_is_root()) {
    printf("Already RPL root\n");
    return;
  }

  NETSTACK_ROUTING.root_set_prefix(NULL, NULL);  
  NETSTACK_ROUTING.root_start();                  

  printf("Created RPL DAG - this node is root\n");
}
/*---------------------------------------------------------------------------*/
PROCESS(unicast_receiver_process, "Unicast receiver process");
AUTOSTART_PROCESSES(&unicast_receiver_process);
/*---------------------------------------------------------------------------*/
PROCESS_THREAD(unicast_receiver_process, ev, data)
{

  PROCESS_BEGIN();

  print_addresses();

  create_rpl_dag();
  
  simple_udp_register(&unicast_connection, UDP_PORT, NULL, UDP_PORT, receiver);

  printf("Receiver ready on UDP port %d\n", UDP_PORT);
  printf("Waiting for packets...\n");
  while(1) {
    PROCESS_WAIT_EVENT();
  }

  PROCESS_END();
}
/*---------------------------------------------------------------------------*/
