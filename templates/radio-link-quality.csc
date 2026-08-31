<?xml version="1.0" encoding="UTF-8"?>
<simconf version="2023090101">
  <simulation>
    <title>radio-link-quality</title>
    <randomseed>generated</randomseed>
    <motedelay_us>1000000</motedelay_us>
    
    <radiomedium>
      org.contikios.cooja.radiomediums.UDGM
      <transmitting_range>50.0</transmitting_range>
      <interference_range>100.0</interference_range>
      <success_ratio_tx>1.0</success_ratio_tx>
      <success_ratio_rx>1.0</success_ratio_rx>
    </radiomedium>
    
<!-- 
    <radiomedium>
      org.contikios.cooja.radiomediums.LogisticLoss
      <transmitting_range>{{TRANSMITTING_RANGE}}</transmitting_range>
      <success_ratio_tx>1.0</success_ratio_tx>
      <rx_sensitivity>{{RX_SENSITIVITY_DBM}}</rx_sensitivity>
      <rssi_inflection_point>{{RSSI_INFLECTION_POINT}}</rssi_inflection_point>
      <path_loss_exponent>{{PATH_LOSS_EXPONENT}}</path_loss_exponent>
      <awgn_sigma>{{AWGN_SIGMA}}</awgn_sigma>
      <enable_time_variation>true</enable_time_variation>
      <time_variation_min_pl_db>-10.0</time_variation_min_pl_db>
      <time_variation_max_pl_db>10.0</time_variation_max_pl_db>
    </radiomedium>
-->
<!--
    <radiomedium>
      org.contikios.cooja.radiomediums.LogisticLoss
      <transmitting_range>50</transmitting_range>
      <success_ratio_tx>1.0</success_ratio_tx>
      <rx_sensitivity>-100</rx_sensitivity>
      <rssi_inflection_point>-94.7743</rssi_inflection_point>
      <path_loss_exponent>1.5162</path_loss_exponent>
      <awgn_sigma>18.7350</awgn_sigma>
      <enable_time_variation>true</enable_time_variation>
      <time_variation_min_pl_db>-10.0</time_variation_min_pl_db>
      <time_variation_max_pl_db>10.0</time_variation_max_pl_db>
    </radiomedium>
-->
    <events>
      <logoutput>40000</logoutput>
    </events>
    <motetype>
      org.contikios.cooja.mspmote.Z1MoteType
      <description>receiver</description>
      <firmware>[CONTIKI_DIR]/examples/radio-link-quality/build/z1/receiver.z1</firmware>
      <moteinterface>org.contikios.cooja.interfaces.Position</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.IPAddress</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.Mote2MoteRelations</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.MoteAttributes</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspClock</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspMoteID</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspButton</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.Msp802154Radio</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspDefaultSerial</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspLED</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspDebugOutput</moteinterface>
      <mote>
        <interface_config>
          org.contikios.cooja.interfaces.Position
          <pos x="65.6334232317246" y="72.2084010804065" z="-0.019459381784958523" />
        </interface_config>
        <interface_config>
          org.contikios.cooja.mspmote.interfaces.MspMoteID
          <id>1</id>
        </interface_config>
      </mote>
    </motetype>
    <motetype>
      org.contikios.cooja.mspmote.Z1MoteType
      <description>sender-3</description>
      <firmware>[CONTIKI_DIR]/examples/radio-link-quality/build/z1/sender.z1</firmware>
      <moteinterface>org.contikios.cooja.interfaces.Position</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.IPAddress</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.Mote2MoteRelations</moteinterface>
      <moteinterface>org.contikios.cooja.interfaces.MoteAttributes</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspClock</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspMoteID</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspButton</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.Msp802154Radio</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspDefaultSerial</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspLED</moteinterface>
      <moteinterface>org.contikios.cooja.mspmote.interfaces.MspDebugOutput</moteinterface>
      <mote>
        <interface_config>
          org.contikios.cooja.interfaces.Position
          <pos x="99.10568759098491" y="97.57655369645002" z="-0.017563127355417426" />
        </interface_config>
        <interface_config>
          org.contikios.cooja.mspmote.interfaces.MspMoteID
          <id>2</id>
        </interface_config>
      </mote>
      <mote>
        <interface_config>
          org.contikios.cooja.interfaces.Position
          <pos x="83.61337393609526" y="72.9862907107102" z="-0.0315979119541939" />
        </interface_config>
        <interface_config>
          org.contikios.cooja.mspmote.interfaces.MspMoteID
          <id>3</id>
        </interface_config>
      </mote>
      <mote>
        <interface_config>
          org.contikios.cooja.interfaces.Position
          <pos x="71.14433897269072" y="88.91406384386461" z="-0.005099772245433898" />
        </interface_config>
        <interface_config>
          org.contikios.cooja.mspmote.interfaces.MspMoteID
          <id>4</id>
        </interface_config>
      </mote>
    </motetype>
  </simulation>
  <plugin>
    org.contikios.cooja.plugins.Visualizer
    <plugin_config>
      <moterelations>true</moterelations>
      <skin>org.contikios.cooja.plugins.skins.IDVisualizerSkin</skin>
      <skin>org.contikios.cooja.plugins.skins.GridVisualizerSkin</skin>
      <skin>org.contikios.cooja.plugins.skins.TrafficVisualizerSkin</skin>
      <skin>org.contikios.cooja.plugins.skins.UDGMVisualizerSkin</skin>
      <viewport>3.8077658591174544 0.0 0.0 3.8077658591174544 -63.97731425937332 -134.75067709555753</viewport>
    </plugin_config>
    <bounds x="1" y="1" height="431" width="402" />
  </plugin>
  <plugin>
    org.contikios.cooja.plugins.LogListener
    <plugin_config>
      <filter />
      <formatted_time />
      <coloring />
    </plugin_config>
    <bounds x="730" y="0" height="200" width="337" z="2" />
  </plugin>
  <plugin>
    org.contikios.cooja.plugins.TimeLine
    <plugin_config>
      <mote>0</mote>
      <mote>1</mote>
      <mote>2</mote>
      <mote>3</mote>
      <showRadioRXTX />
      <showRadioHW />
      <showLEDs />
      <zoomfactor>500.0</zoomfactor>
    </plugin_config>
    <bounds x="0" y="433" height="166" width="1070" z="3" />
  </plugin>
  <plugin>
    org.contikios.cooja.plugins.RadioLogger
    <plugin_config>
      <split>122</split>
      <formatted_time />
    </plugin_config>
    <bounds x="402" y="202" height="228" width="668" z="1" />
  </plugin>
  <plugin>
    org.contikios.cooja.plugins.BaseRSSIconf
    <bounds x="403" y="0" height="201" width="327" z="4" />
  </plugin>
</simconf>
