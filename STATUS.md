# RQT Graph Focus - Projektstatus

## Überblick

Fork von `rqt_graph` mit zusätzlichen Features:
- **Click-to-Focus**: Klick auf Node/Topic filtert Graph auf verbundene Elemente
- **Connection List Panel**: Zeigt Publishers/Subscribers des ausgewählten Elements

**Repository:** https://github.com/STH1/rqt_graph
**Branch:** `humble`
**Paketname:** `rqt_graph_focus` (kann parallel zum Original installiert werden)

---

## Implementierte Features

### 1. Click-Detection (`interactive_graphics_view.py`)
- Signal `item_clicked` das beim Klicken auf Graph-Elemente emittiert wird
- Unterscheidet zwischen Klick (< 5px Bewegung) und Drag/Pan
- Extrahiert URL aus geklicktem Item via `toolTip()`

### 2. Connection Panel (UI in `RosGraph.ui`)
- QSplitter Layout mit Graph links, Panel rechts
- Widgets:
  - `selected_item_label` - Zeigt ausgewähltes Element
  - `clear_focus_button` - Setzt Focus zurück
  - `publishers_list` - Liste der Publisher
  - `subscribers_list` - Liste der Subscriber
  - `publishers_header` / `subscribers_header` - Dynamische Labels

### 3. Focus-Logik (`ros_graph.py`)
- State: `_focused_item`, `_focused_item_type`
- Methoden:
  - `_on_item_clicked()` - Verarbeitet Klicks
  - `_clear_focus()` - Setzt Focus zurück
  - `_get_connected_elements()` - Ermittelt verbundene Nodes/Topics
  - `_update_connection_list()` - Aktualisiert Panel
  - `_on_list_item_double_clicked()` - Navigation per Doppelklick
- Filter-Integration in `_generate_dotcode()`

---

## Geänderte Dateien

| Datei | Änderungen |
|-------|------------|
| `package.xml` | Name → `rqt_graph_focus`, neue Beschreibung |
| `setup.py` | package_name, entry_points, scripts |
| `plugin.xml` | Klasse → `RosGraphFocus`, Label → "Node Graph (Focus)" |
| `resource/RosGraph.ui` | Splitter + Connection Panel hinzugefügt |
| `src/rqt_graph_focus/interactive_graphics_view.py` | Click-Detection |
| `src/rqt_graph_focus/ros_graph.py` | Focus-Logik, Connection List |
| `src/rqt_graph_focus/dotcode.py` | Import geändert |
| `src/rqt_graph_focus/main.py` | Import geändert |

---

## Bekanntes Problem

Beim Starten auf dem Jetson erscheint der Fehler:

```
AssertionError: "dot" with args ['-Tdot', '/tmp/...'] returned code: 1
```

**Ursache:** Unklar. Das Original `rqt_graph` funktioniert, graphviz ist installiert.

**Mögliche Lösungen zum Testen:**
1. RQT-Config löschen:
   ```bash
   rm -rf ~/.config/ros.org/rqt_gui.ini
   rm -rf ~/.config/ros.org/rqt_gui/
   ```
2. Mit Debug starten:
   ```bash
   ros2 run rqt_graph_focus rqt_graph_focus --force-discover
   ```
3. Python-Import testen:
   ```bash
   python3 -c "from rqt_graph_focus.ros_graph import RosGraph; print('OK')"
   ```

---

## Installation auf Jetson (ROS2 Humble)

```bash
# 1. Repository klonen
cd ~/git
git clone -b humble https://github.com/STH1/rqt_graph.git rqt_graph_focus

# 2. Bauen
cd ~/git/rqt_graph_focus
colcon build --packages-select rqt_graph_focus

# 3. Sourcen
source /opt/ros/humble/setup.bash
source ~/git/rqt_graph_focus/install/setup.bash

# 4. Starten
ros2 run rqt_graph_focus rqt_graph_focus --force-discover
```

**Optional in `~/.bashrc`:**
```bash
source ~/git/rqt_graph_focus/install/setup.bash
```

---

## Lokale Entwicklung (Windows)

Repository: `C:\Users\Simon\OneDrive\Dokumente\git\rqt_graph`

```bash
# Branch wechseln
git checkout humble

# Änderungen committen
git add -A
git commit -m "Beschreibung"
git push origin humble
```

**Remotes:**
- `origin` = STH1/rqt_graph (Fork)
- `upstream` = ros-visualization/rqt_graph (Original)

---

## Nächste Schritte

1. [ ] Debug des "dot returned code: 1" Fehlers auf Jetson
2. [ ] Testen ob Click-Detection funktioniert
3. [ ] Testen ob Connection Panel korrekt aktualisiert wird
4. [ ] Optional: Styling/UX verbessern

---

## Architektur-Notizen

### Datenstrukturen (rosgraph2_impl.py)
- `Graph.nn_nodes` - Set von Node-Namen
- `Graph.nt_nodes` - Set von Topic-Namen (mit Space-Prefix: `' /topic'`)
- `Graph.nn_edges` / `Graph.nt_edges` - EdgeList mit `edges_by_start`/`edges_by_end`
- `Edge` - start, end, label, qos

### URL-Format in DOT
- Nodes: `/node_name` oder `/node_name (DEAD)`
- Topics: `topic:/topic_name`

### Graph-Pipeline
```
ROS2 System
    ↓
Graph._graph_refresh()
    ↓
RosGraphDotcodeGenerator.generate_dotcode()
    ↓
DOT Code (graphviz)
    ↓
DotToQtGenerator.dotcode_to_qt_items()
    ↓
QGraphicsScene
```
