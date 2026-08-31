#!/usr/bin/env python3
# =============================================================================
# generate_csc.py
# Injects IoT-LAB node positions AND LogisticLoss radio parameters
# into a Cooja .csc template.
#
# Usage:
#   python3 generate_csc.py \
#       --template     templates/radio-link-quality.csc \
#       --positions    node_positions.json \
#       --firmware-dir ~/contiki-ng/examples/radio-link-quality \
#       --duration     60 \
#       --speed-limit  -1 \
#       --output       simulation.csc \
#       --rx-sensitivity       -100.0 \
#       --rssi-inflection-point -50.0 \
#       --transmitting-range    40.0  \
#       --path-loss-exponent     3.0  \
#       --awgn-sigma             7.0
# =============================================================================

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

ET.register_namespace("", "")


def indent(elem, level=0):
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad


# Map CLI arg name → XML tag name inside <radiomedium>
RADIO_PARAM_TAGS = {
    "rx_sensitivity":        "rx_sensitivity",
    "rssi_inflection_point": "rssi_inflection_point",
    "transmitting_range":    "transmitting_range",
    "path_loss_exponent":    "path_loss_exponent",
    "awgn_sigma":            "awgn_sigma",
}


def inject_radio_params(sim, radio_params):
    """
    Find the active LogisticLoss <radiomedium> block and update
    each parameter tag. Creates the tag if it doesn't exist yet.
    Skips None values (parameter not supplied on CLI).
    """
    radiomedium = None
    for rm in sim.findall("radiomedium"):
        # The class name is the text content of the element itself
        if rm.text and "LogisticLoss" in rm.text:
            radiomedium = rm
            break

    if radiomedium is None:
        print("  ⚠  No LogisticLoss radiomedium block found — skipping radio param injection")
        return

    for param_key, xml_tag in RADIO_PARAM_TAGS.items():
        value = radio_params.get(param_key)
        if value is None:
            continue
        el = radiomedium.find(xml_tag)
        if el is not None:
            el.text = str(value)
        else:
            new_el = ET.SubElement(radiomedium, xml_tag)
            new_el.text = str(value)
        print(f"  ✓ {xml_tag} = {value}")


def generate_csc(template_path, positions_data, firmware_dir, duration_min,
                 output_path, speed_limit, radio_params=None):

    tree = ET.parse(template_path)
    root = tree.getroot()
    sim  = root.find("simulation")

    nodes = positions_data["nodes"]

    # Title
    title_el = sim.find("title")
    if title_el is not None:
        title_el.text = "radio-link-quality-fitiotlab"

    # Speed limit
    speed_el = sim.find("speedlimit")
    if speed_el is not None:
        speed_el.text = str(speed_limit)
    else:
        speed_el = ET.Element("speedlimit")
        speed_el.text = str(speed_limit)
        title_index = list(sim).index(title_el) if title_el is not None else 0
        sim.insert(title_index + 1, speed_el)

    if speed_limit == "-1":
        print("  ✓ Speed limit: unlimited (fastest possible)")
    else:
        print(f"  ✓ Speed limit: {speed_limit}× real time")

    # ── Radio parameters (new) ────────────────────────────────────────────────
    if radio_params:
        print("  → Injecting LogisticLoss radio parameters...")
        inject_radio_params(sim, radio_params)

    # ── Node positions & firmware ─────────────────────────────────────────────
    for motetype in sim.findall("motetype"):
        desc_el = motetype.find("description")
        fw_el   = motetype.find("firmware")
        if desc_el is None:
            continue

        desc        = desc_el.text.strip()
        is_receiver = (desc == "receiver")

        if fw_el is not None:
            if is_receiver:
                fw_el.text = f"{firmware_dir}/build/z1/receiver.z1"
            else:
                fw_el.text = f"{firmware_dir}/build/z1/sender.z1"

        role = "receiver" if is_receiver else "sender"

        # Remove all template motes and rebuild from positions data
        for mote in motetype.findall("mote"):
            motetype.remove(mote)

        role_nodes = sorted(
            [info for info in nodes.values() if info["role"] == role],
            key=lambda n: n["cooja_id"]
        )
        for node_info in role_nodes:
            cooja_id = node_info["cooja_id"]
            mote_el  = ET.SubElement(motetype, "mote")

            pos_iface      = ET.SubElement(mote_el, "interface_config")
            pos_iface.text = "org.contikios.cooja.interfaces.Position"
            pos_el         = ET.SubElement(pos_iface, "pos")
            pos_el.set("x", str(node_info["x"]))
            pos_el.set("y", str(node_info["y"]))
            pos_el.set("z", str(node_info["z"]))

            id_iface      = ET.SubElement(mote_el, "interface_config")
            id_iface.text = "org.contikios.cooja.mspmote.interfaces.MspMoteID"
            id_el         = ET.SubElement(id_iface, "id")
            id_el.text    = str(cooja_id)

            print(f"  ✓ Mote {cooja_id} ({role}) → x={node_info['x']}, y={node_info['y']}")

    # ── Log output buffer ─────────────────────────────────────────────────────
    duration_s      = duration_min * 60
    estimated_lines = duration_s * 30 * 3
    events_el = sim.find("events/logoutput")
    if events_el is not None:
        events_el.text = str(max(40000, estimated_lines))

    # ── ScriptRunner ──────────────────────────────────────────────────────────
    log_output_path = os.path.join(
        os.path.dirname(os.path.abspath(output_path)), "cooja", "loglistener.txt"
    ).replace("\\", "/")

    duration_ms = duration_min * 60 * 1000
    script_code = (
        f"TIMEOUT({duration_ms}, log.testOK());\n"
        "var FileWriter = java.io.FileWriter;\n"
        "var BufferedWriter = java.io.BufferedWriter;\n"
        "var File = java.io.File;\n"
        f"new File(\"{log_output_path}\").getParentFile().mkdirs();\n"
        f"var bw = new BufferedWriter(new FileWriter(\"{log_output_path}\"));\n"
        "while (true) {\n"
        "  YIELD();\n"
        "  bw.write((time/1000) + \"\\t\" + \"ID:\" + id + \"\\t\" + msg);\n"
        "  bw.newLine();\n"
        "  bw.flush();\n"
        "}"
    )

    for plugin in list(root.findall("plugin")):
        if "ScriptRunner" in (plugin.text or ""):
            root.remove(plugin)

    script_plugin  = ET.SubElement(root, "plugin")
    script_plugin.text = "org.contikios.cooja.plugins.ScriptRunner"
    plugin_config  = ET.SubElement(script_plugin, "plugin_config")
    script_el      = ET.SubElement(plugin_config, "script")
    script_el.text = script_code
    active_el      = ET.SubElement(plugin_config, "active")
    active_el.text = "true"

    print(f"  ✓ ScriptRunner injected → {log_output_path}")

    indent(root)
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    print(f"  ✓ .csc written: {output_path}")


def _iotlab_id(node_info):
    try:
        return node_info["network_address"].split("-")[1].split(".")[0]
    except Exception:
        return "?"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template",               required=True)
    parser.add_argument("--positions",              required=True)
    parser.add_argument("--firmware-dir",           required=True)
    parser.add_argument("--duration",               type=int, default=5)
    parser.add_argument("--output",                 required=True)
    parser.add_argument("--speed-limit",            default="-1")

    # Radio parameters (all optional — if omitted, template value is kept)
    parser.add_argument("--rx-sensitivity",         type=float, default=None)
    parser.add_argument("--rssi-inflection-point",  type=float, default=None)
    parser.add_argument("--transmitting-range",     type=float, default=None)
    parser.add_argument("--path-loss-exponent",     type=float, default=None)
    parser.add_argument("--awgn-sigma",             type=float, default=None)

    args = parser.parse_args()

    with open(args.positions) as f:
        positions_data = json.load(f)

    radio_params = {
        "rx_sensitivity":        args.rx_sensitivity,
        "rssi_inflection_point": args.rssi_inflection_point,
        "transmitting_range":    args.transmitting_range,
        "path_loss_exponent":    args.path_loss_exponent,
        "awgn_sigma":            args.awgn_sigma,
    }

    print(f"  → Injecting positions for {len(positions_data['nodes'])} nodes...")
    generate_csc(
        template_path  = args.template,
        positions_data = positions_data,
        firmware_dir   = args.firmware_dir,
        duration_min   = args.duration,
        output_path    = args.output,
        speed_limit    = args.speed_limit,
        radio_params   = radio_params,
    )


if __name__ == "__main__":
    main()