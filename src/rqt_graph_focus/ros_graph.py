# Copyright (c) 2011, Dirk Thomas, TU Darmstadt
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
#   * Neither the name of the TU Darmstadt nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import division
import os
import re

from ament_index_python import get_resource
from python_qt_binding import loadUi
from python_qt_binding.QtCore import QAbstractListModel, QFile, QIODevice, Qt, Signal
from python_qt_binding.QtGui import QIcon, QImage, QPainter
from python_qt_binding.QtWidgets import QCompleter, QFileDialog, QGraphicsScene, QWidget
from python_qt_binding.QtSvg import QSvgGenerator

from rqt_graph_focus.rosgraph2_impl import Graph

from qt_dotgraph.dot_to_qt import DotToQtGenerator
# pydot requires some hacks
from qt_dotgraph.pydotfactory import PydotFactory
from rqt_gui_py.plugin import Plugin
# TODO: use pygraphviz instead, but non-deterministic layout will first be resolved in graphviz 2.30
# from qtgui_plugin.pygraphvizfactory import PygraphvizFactory

from .dotcode import \
    RosGraphDotcodeGenerator, NODE_NODE_GRAPH, NODE_TOPIC_ALL_GRAPH, NODE_TOPIC_GRAPH
from .interactive_graphics_view import InteractiveGraphicsView

try:
    unicode
    # we're on python2, or the "unicode" function has already been defined elsewhere
except NameError:
    unicode = str
    # we're on python3


class RepeatedWordCompleter(QCompleter):

    """A completer that completes multiple times from a list"""

    def init(self, parent=None):
        QCompleter.init(self, parent)

    def pathFromIndex(self, index):
        path = QCompleter.pathFromIndex(self, index)
        lst = unicode(self.widget().text()).split(',')
        if len(lst) > 1:
            path = '%s, %s' % (','.join(lst[:-1]), path)
        return path

    def splitPath(self, path):
        path = unicode(path.split(',')[-1]).lstrip(' ')
        return [path]


class NamespaceCompletionModel(QAbstractListModel):

    """Ros package and stacknames"""

    def __init__(self, linewidget, topics_only):
        super(NamespaceCompletionModel, self).__init__(linewidget)
        self.names = []

    def refresh(self, names):
        namesset = set()
        for n in names:
            namesset.add(unicode(n).strip())
            namesset.add("-%s" % (unicode(n).strip()))
        self.names = sorted(namesset)

    def rowCount(self, parent):
        return len(self.names)

    def data(self, index, role):
        if index.isValid() and (role == Qt.DisplayRole or role == Qt.EditRole):
            return self.names[index.row()]
        return None


class RosGraph(Plugin):

    _deferred_fit_in_view = Signal()

    def __init__(self, context):
        super(RosGraph, self).__init__(context)
        self._node = context.node
        self._logger = self._node.get_logger().get_child('rqt_graph_focus.ros_graph.RosGraph')
        self.initialized = False
        self.setObjectName('RosGraph')

        self._graph = None
        self._current_dotcode = None

        # Focus state for click-to-focus feature
        self._focused_item = None       # Name of focused element
        self._focused_item_type = None  # 'node' or 'topic'

        self._widget = QWidget()

        # factory builds generic dotcode items
        self.dotcode_factory = PydotFactory()
        # self.dotcode_factory = PygraphvizFactory()
        # generator builds rosgraph
        self.dotcode_generator = RosGraphDotcodeGenerator(self._node)
        # dot_to_qt transforms into Qt elements using dot layout
        self.dot_to_qt = DotToQtGenerator()

        _, package_path = get_resource('packages', 'rqt_graph_focus')
        ui_file = os.path.join(package_path, 'share', 'rqt_graph_focus', 'resource', 'RosGraph.ui')
        loadUi(ui_file, self._widget, {'InteractiveGraphicsView': InteractiveGraphicsView})
        self._widget.setObjectName('RosGraphUi')
        if context.serial_number() > 1:
            self._widget.setWindowTitle(
                self._widget.windowTitle() + (' (%d)' % context.serial_number()))

        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(Qt.white)
        self._widget.graphics_view.setScene(self._scene)

        self._widget.graph_type_combo_box.insertItem(0, self.tr('Nodes only'), NODE_NODE_GRAPH)
        self._widget.graph_type_combo_box.insertItem(
            1, self.tr('Nodes/Topics (active)'), NODE_TOPIC_GRAPH)
        self._widget.graph_type_combo_box.insertItem(
            2, self.tr('Nodes/Topics (all)'), NODE_TOPIC_ALL_GRAPH)
        self._widget.graph_type_combo_box.setCurrentIndex(0)
        self._widget.graph_type_combo_box.currentIndexChanged.connect(self._refresh_rosgraph)

        self.node_completionmodel = NamespaceCompletionModel(self._widget.filter_line_edit, False)
        completer = RepeatedWordCompleter(self.node_completionmodel, self)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setWrapAround(True)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._widget.filter_line_edit.editingFinished.connect(self._refresh_rosgraph)
        self._widget.filter_line_edit.setCompleter(completer)

        self.topic_completionmodel = NamespaceCompletionModel(
            self._widget.topic_filter_line_edit, False)
        topic_completer = RepeatedWordCompleter(self.topic_completionmodel, self)
        topic_completer.setCompletionMode(QCompleter.PopupCompletion)
        topic_completer.setWrapAround(True)
        topic_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._widget.topic_filter_line_edit.editingFinished.connect(self._refresh_rosgraph)
        self._widget.topic_filter_line_edit.setCompleter(topic_completer)

        self._widget.namespace_cluster_spin_box.valueChanged.connect(self._refresh_rosgraph)
        self._widget.actionlib_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.dead_sinks_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.leaf_topics_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.quiet_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.unreachable_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.group_tf_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.hide_tf_nodes_check_box.clicked.connect(self._refresh_rosgraph)
        self._widget.group_image_check_box.clicked.connect(self._refresh_rosgraph)

        self._widget.refresh_graph_push_button.setIcon(QIcon.fromTheme('view-refresh'))
        self._widget.refresh_graph_push_button.pressed.connect(self._update_rosgraph)

        self._widget.highlight_connections_check_box.toggled.connect(self._redraw_graph_view)
        self._widget.auto_fit_graph_check_box.toggled.connect(self._redraw_graph_view)
        self._widget.fit_in_view_push_button.setIcon(QIcon.fromTheme('view-fullscreen'))
        self._widget.fit_in_view_push_button.pressed.connect(self._fit_in_view)

        self._widget.load_dot_push_button.setIcon(QIcon.fromTheme('document-open'))
        self._widget.load_dot_push_button.pressed.connect(self._load_dot)
        self._widget.save_dot_push_button.setIcon(QIcon.fromTheme('document-save-as'))
        self._widget.save_dot_push_button.pressed.connect(self._save_dot)
        self._widget.save_as_svg_push_button.setIcon(QIcon.fromTheme('document-save-as'))
        self._widget.save_as_svg_push_button.pressed.connect(self._save_svg)
        self._widget.save_as_image_push_button.setIcon(QIcon.fromTheme('image'))
        self._widget.save_as_image_push_button.pressed.connect(self._save_image)

        # Connect click-to-focus signals
        self._widget.graphics_view.item_clicked.connect(self._on_item_clicked)
        self._widget.clear_focus_button.clicked.connect(self._clear_focus)

        # Connect list item double-click for navigation
        self._widget.publishers_list.itemDoubleClicked.connect(
            self._on_list_item_double_clicked)
        self._widget.subscribers_list.itemDoubleClicked.connect(
            self._on_list_item_double_clicked)

        self._update_rosgraph()
        self._deferred_fit_in_view.connect(self._fit_in_view, Qt.QueuedConnection)
        self._deferred_fit_in_view.emit()

        context.add_widget(self._widget)

    def save_settings(self, plugin_settings, instance_settings):
        instance_settings.set_value(
            'graph_type_combo_box_index', self._widget.graph_type_combo_box.currentIndex())
        instance_settings.set_value('filter_line_edit_text', self._widget.filter_line_edit.text())
        instance_settings.set_value(
            'topic_filter_line_edit_text', self._widget.topic_filter_line_edit.text())
        instance_settings.set_value(
            'namespace_cluster_spin_box_value', self._widget.namespace_cluster_spin_box.value())
        instance_settings.set_value(
            'actionlib_check_box_state', self._widget.actionlib_check_box.isChecked())
        instance_settings.set_value(
            'dead_sinks_check_box_state', self._widget.dead_sinks_check_box.isChecked())
        instance_settings.set_value(
            'leaf_topics_check_box_state', self._widget.leaf_topics_check_box.isChecked())
        instance_settings.set_value(
            'quiet_check_box_state', self._widget.quiet_check_box.isChecked())
        instance_settings.set_value(
            'unreachable_check_box_state', self._widget.unreachable_check_box.isChecked())
        instance_settings.set_value(
            'auto_fit_graph_check_box_state', self._widget.auto_fit_graph_check_box.isChecked())
        instance_settings.set_value(
            'highlight_connections_check_box_state',
            self._widget.highlight_connections_check_box.isChecked())
        instance_settings.set_value(
            'group_tf_check_box_state', self._widget.group_tf_check_box.isChecked())
        instance_settings.set_value(
            'hide_tf_nodes_check_box_state', self._widget.hide_tf_nodes_check_box.isChecked())
        instance_settings.set_value(
            'group_image_check_box_state', self._widget.group_image_check_box.isChecked())
        instance_settings.set_value(
            'hide_dynamic_reconfigure_check_box_state',
            self._widget.hide_dynamic_reconfigure_check_box.isChecked())
        instance_settings.set_value(
            'main_splitter_state', self._widget.main_splitter.saveState())

    def restore_settings(self, plugin_settings, instance_settings):
        self._widget.graph_type_combo_box.setCurrentIndex(
            int(instance_settings.value('graph_type_combo_box_index', 0)))
        self._widget.filter_line_edit.setText(instance_settings.value('filter_line_edit_text', '/'))
        self._widget.topic_filter_line_edit.setText(
            instance_settings.value('topic_filter_line_edit_text', '/'))
        self._widget.namespace_cluster_spin_box.setValue(
            int(instance_settings.value('namespace_cluster_spin_box_value', 2)))
        self._widget.actionlib_check_box.setChecked(
            instance_settings.value('actionlib_check_box_state', True) in [True, 'true'])
        self._widget.dead_sinks_check_box.setChecked(
            instance_settings.value('dead_sinks_check_box_state', True) in [True, 'true'])
        self._widget.leaf_topics_check_box.setChecked(
            instance_settings.value('leaf_topics_check_box_state', True) in [True, 'true'])
        self._widget.quiet_check_box.setChecked(
            instance_settings.value('quiet_check_box_state', True) in [True, 'true'])
        self._widget.unreachable_check_box.setChecked(
            instance_settings.value('unreachable_check_box_state', True) in [True, 'true'])
        self._widget.auto_fit_graph_check_box.setChecked(
            instance_settings.value('auto_fit_graph_check_box_state', True) in [True, 'true'])
        self._widget.highlight_connections_check_box.setChecked(
            instance_settings.value('highlight_connections_check_box_state', True) in
            [True, 'true'])
        self._widget.hide_tf_nodes_check_box.setChecked(
            instance_settings.value('hide_tf_nodes_check_box_state', False) in [True, 'true'])
        self._widget.group_tf_check_box.setChecked(
            instance_settings.value('group_tf_check_box_state', True) in [True, 'true'])
        self._widget.group_image_check_box.setChecked(
            instance_settings.value('group_image_check_box_state', True) in [True, 'true'])
        self._widget.hide_dynamic_reconfigure_check_box.setChecked(
            instance_settings.value('hide_dynamic_reconfigure_check_box_state', True) in
            [True, 'true'])
        splitter_state = instance_settings.value('main_splitter_state', None)
        if splitter_state is not None:
            self._widget.main_splitter.restoreState(splitter_state)
        self.initialized = True
        self._refresh_rosgraph()

    def _update_rosgraph(self):
        # re-enable controls customizing fetched ROS graph
        self._widget.graph_type_combo_box.setEnabled(True)
        self._widget.filter_line_edit.setEnabled(True)
        self._widget.topic_filter_line_edit.setEnabled(True)
        self._widget.namespace_cluster_spin_box.setEnabled(True)
        self._widget.actionlib_check_box.setEnabled(True)
        self._widget.dead_sinks_check_box.setEnabled(True)
        self._widget.leaf_topics_check_box.setEnabled(True)
        self._widget.quiet_check_box.setEnabled(True)
        self._widget.unreachable_check_box.setEnabled(True)
        self._widget.group_tf_check_box.setEnabled(True)
        self._widget.hide_tf_nodes_check_box.setEnabled(True)
        self._widget.group_image_check_box.setEnabled(True)
        self._widget.hide_dynamic_reconfigure_check_box.setEnabled(True)

        self._graph = Graph(self._node)
        self._graph.set_node_stale(5.0)
        self._graph.update()
        self.node_completionmodel.refresh(self._graph.nn_nodes)
        self.topic_completionmodel.refresh(self._graph.nt_nodes)
        self._refresh_rosgraph()

    def _refresh_rosgraph(self):
        if not self.initialized:
            return
        self._update_graph_view(self._generate_dotcode())

    def _generate_dotcode(self):
        ns_filter = self._widget.filter_line_edit.text()
        topic_filter = self._widget.topic_filter_line_edit.text()

        # Apply focus filter if active
        if self._focused_item:
            connected_nodes, connected_topics = self._get_connected_elements(
                self._focused_item, self._focused_item_type)
            if connected_nodes:
                # Use exact regex matches to avoid prefix-matching
                # (e.g., /camera-left should not match /camera-left-depth)
                ns_filter = ','.join('^' + re.escape(n) + '$' for n in connected_nodes)
            if connected_topics:
                # Use exact regex matches for topics too
                topic_filter = ','.join('^' + re.escape(t) + '$' for t in connected_topics)

        graph_mode = self._widget.graph_type_combo_box.itemData(
            self._widget.graph_type_combo_box.currentIndex())
        orientation = 'LR'
        namespace_cluster = self._widget.namespace_cluster_spin_box.value()
        accumulate_actions = self._widget.actionlib_check_box.isChecked()
        hide_dead_end_topics = self._widget.dead_sinks_check_box.isChecked()
        hide_single_connection_topics = self._widget.leaf_topics_check_box.isChecked()
        quiet = self._widget.quiet_check_box.isChecked()
        unreachable = self._widget.unreachable_check_box.isChecked()
        group_tf_nodes = self._widget.group_tf_check_box.isChecked()
        hide_tf_nodes = self._widget.hide_tf_nodes_check_box.isChecked()
        group_image_nodes = self._widget.group_image_check_box.isChecked()
        hide_dynamic_reconfigure = self._widget.hide_dynamic_reconfigure_check_box.isChecked()

        return self.dotcode_generator.generate_dotcode(
            rosgraphinst=self._graph,
            ns_filter=ns_filter,
            topic_filter=topic_filter,
            graph_mode=graph_mode,
            hide_single_connection_topics=hide_single_connection_topics,
            hide_dead_end_topics=hide_dead_end_topics,
            cluster_namespaces_level=namespace_cluster,
            accumulate_actions=accumulate_actions,
            dotcode_factory=self.dotcode_factory,
            orientation=orientation,
            quiet=quiet,
            unreachable=unreachable,
            group_tf_nodes=group_tf_nodes,
            hide_tf_nodes=hide_tf_nodes,
            group_image_nodes=group_image_nodes,
            hide_dynamic_reconfigure=hide_dynamic_reconfigure,
            selected_item=self._focused_item,
            selected_item_type=self._focused_item_type)

    def _update_graph_view(self, dotcode):
        if dotcode == self._current_dotcode:
            return
        self._current_dotcode = dotcode
        self._redraw_graph_view()

    def _generate_tool_tip(self, url):
        if url is not None and ':' in url:
            item_type, item_path = url.split(':', 1)
            if item_type == 'node':
                tool_tip = 'Node:\n  %s' % (item_path)
                service_names_and_types = self._node.get_service_names_and_types()
                if service_names_and_types:
                    tool_tip += '\nServices:'
                    for service_name, service_type in service_names_and_types:
                        tool_tip += '\n  %s [%s]' % (service_name, service_type)
                return tool_tip
            elif item_type == 'topic':
                for topic_name, topic_type in self._node.get_topic_names_and_types():
                    if topic_name in item_path:
                        return 'Topic:\n  %s\nType:\n  %s' % (topic_name, topic_type)
                return 'No topic with item path {}'.format(item_path)
        return url

    def _redraw_graph_view(self):
        self._scene.clear()

        if self._widget.highlight_connections_check_box.isChecked():
            highlight_level = 3
        else:
            highlight_level = 1

        # layout graph and create qt items
        (nodes, edges) = self.dot_to_qt.dotcode_to_qt_items(self._current_dotcode,
                                                            highlight_level=highlight_level,
                                                            same_label_siblings=True,
                                                            scene=self._scene)

        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        if self._widget.auto_fit_graph_check_box.isChecked():
            self._fit_in_view()

    def _load_dot(self, file_name=None):
        if file_name is None:
            file_name, _ = QFileDialog.getOpenFileName(
                self._widget, self.tr('Open graph from file'), None, self.tr('DOT graph (*.dot)'))
            if file_name is None or file_name == '':
                return

        try:
            fh = open(file_name, 'rb')
            dotcode = fh.read()
            fh.close()
        except IOError:
            return

        # disable controls customizing fetched ROS graph
        self._widget.graph_type_combo_box.setEnabled(False)
        self._widget.filter_line_edit.setEnabled(False)
        self._widget.topic_filter_line_edit.setEnabled(False)
        self._widget.namespace_cluster_spin_box.setEnabled(False)
        self._widget.actionlib_check_box.setEnabled(False)
        self._widget.dead_sinks_check_box.setEnabled(False)
        self._widget.leaf_topics_check_box.setEnabled(False)
        self._widget.quiet_check_box.setEnabled(False)
        self._widget.unreachable_check_box.setEnabled(False)
        self._widget.group_tf_check_box.setEnabled(False)
        self._widget.hide_tf_nodes_check_box.setEnabled(False)
        self._widget.group_image_check_box.setEnabled(False)
        self._widget.hide_dynamic_reconfigure_check_box.setEnabled(False)

        self._update_graph_view(dotcode)

    def _fit_in_view(self):
        self._widget.graphics_view.fitInView(self._scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def _save_dot(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self._widget, self.tr('Save as DOT'), 'rosgraph.dot', self.tr('DOT graph (*.dot)'))
        if file_name is None or file_name == '':
            return

        handle = QFile(file_name)
        if not handle.open(QIODevice.WriteOnly | QIODevice.Text):
            return

        handle.write(self._current_dotcode)
        handle.close()

    def _save_svg(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self._widget, self.tr('Save as SVG'), 'rosgraph.svg',
            self.tr('Scalable Vector Graphic (*.svg)'))
        if file_name is None or file_name == '':
            return

        generator = QSvgGenerator()
        generator.setFileName(file_name)
        generator.setSize((self._scene.sceneRect().size() * 2.0).toSize())

        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter)
        painter.end()

    def _save_image(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self._widget, self.tr('Save as image'), 'rosgraph.png',
            self.tr('Image (*.bmp *.jpg *.png *.tiff)'))
        if file_name is None or file_name == '':
            return

        img = QImage((self._scene.sceneRect().size() * 2.0)
                     .toSize(), QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter)
        painter.end()
        img.save(file_name)

    def _on_item_clicked(self, url):
        """Handle click on a graph item to focus on it."""
        if not url:
            return

        # Parse URL format - can be 'topic:/name' or just '/name' for nodes
        if url.startswith('topic:'):
            self._focused_item = url[6:]  # Remove 'topic:' prefix
            self._focused_item_type = 'topic'
        else:
            # Handle node URLs, remove status suffix like ' (DEAD)'
            self._focused_item = url.split(' ')[0] if ' ' in url else url
            self._focused_item_type = 'node'

        self._widget.clear_focus_button.setEnabled(True)
        self._refresh_rosgraph()
        self._update_connection_list()

    def _clear_focus(self):
        """Clear the focus filter and show full graph."""
        self._focused_item = None
        self._focused_item_type = None
        self._widget.clear_focus_button.setEnabled(False)
        self._refresh_rosgraph()
        self._clear_connection_list()

    def _get_connected_elements(self, item_name, item_type):
        """Get all nodes and topics directly connected to the given item."""
        connected_nodes = set()
        connected_topics = set()

        if self._graph is None:
            return connected_nodes, connected_topics

        if item_type == 'node':
            # Add the focused node itself
            connected_nodes.add(item_name)

            # Find all topics this node publishes to or subscribes from
            for edge in self._graph.nt_edges:
                if edge.start == item_name:
                    # Node publishes to topic (edge.end is topic with space prefix)
                    topic = edge.end[1:] if edge.end.startswith(' ') else edge.end
                    connected_topics.add(topic)
                elif edge.end == item_name:
                    # Node subscribes to topic (edge.start is topic with space prefix)
                    topic = edge.start[1:] if edge.start.startswith(' ') else edge.start
                    connected_topics.add(topic)

            # Also find nodes connected via topics (for node-node graph mode)
            for edge in self._graph.nn_edges:
                if edge.start == item_name:
                    connected_nodes.add(edge.end)
                elif edge.end == item_name:
                    connected_nodes.add(edge.start)

        elif item_type == 'topic':
            topic_node_name = ' ' + item_name  # Topic nodes have space prefix
            connected_topics.add(item_name)

            for edge in self._graph.nt_edges:
                if edge.start == topic_node_name or edge.end == topic_node_name:
                    # Find the node (non-topic) end of the edge
                    if edge.start.startswith(' '):
                        connected_nodes.add(edge.end)
                    else:
                        connected_nodes.add(edge.start)

        return connected_nodes, connected_topics

    def _update_connection_list(self):
        """Update the connection list panel with info about the focused item."""
        if not self._focused_item or not self._graph:
            self._clear_connection_list()
            return

        publishers = []
        subscribers = []
        item_display_name = self._focused_item

        if self._focused_item_type == 'topic':
            # For a topic, show publishing and subscribing nodes
            topic_node_name = ' ' + self._focused_item

            for edge in self._graph.nt_edges:
                if edge.end == topic_node_name:
                    # edge.start is a publishing node
                    publishers.append(edge.start)
                elif edge.start == topic_node_name:
                    # edge.end is a subscribing node
                    subscribers.append(edge.end)

            # Get topic type
            topic_type = self._get_topic_type(self._focused_item)
            if topic_type:
                item_display_name = '%s\n[%s]' % (self._focused_item, topic_type)

            # Update headers for topic
            self._widget.publishers_header.setText('Publishing Nodes:')
            self._widget.subscribers_header.setText('Subscribing Nodes:')

        elif self._focused_item_type == 'node':
            # For a node, show topics it publishes and subscribes to
            for edge in self._graph.nt_edges:
                if edge.start == self._focused_item:
                    # Publishing to edge.end (topic)
                    topic = edge.end[1:] if edge.end.startswith(' ') else edge.end
                    topic_type = self._get_topic_type(topic)
                    if topic_type:
                        publishers.append('%s [%s]' % (topic, topic_type))
                    else:
                        publishers.append(topic)
                elif edge.end == self._focused_item:
                    # Subscribing to edge.start (topic)
                    topic = edge.start[1:] if edge.start.startswith(' ') else edge.start
                    topic_type = self._get_topic_type(topic)
                    if topic_type:
                        subscribers.append('%s [%s]' % (topic, topic_type))
                    else:
                        subscribers.append(topic)

            # Update headers for node
            self._widget.publishers_header.setText('Publishes To:')
            self._widget.subscribers_header.setText('Subscribes To:')

        # Update UI
        self._widget.selected_item_label.setText(item_display_name)

        self._widget.publishers_list.clear()
        for pub in sorted(publishers):
            self._widget.publishers_list.addItem(pub)

        self._widget.subscribers_list.clear()
        for sub in sorted(subscribers):
            self._widget.subscribers_list.addItem(sub)

    def _get_topic_type(self, topic_name):
        """Get the message type for a topic."""
        for name, types in self._node.get_topic_names_and_types():
            if name == topic_name:
                return types[0] if types else None
        return None

    def _clear_connection_list(self):
        """Clear the connection list panel."""
        self._widget.selected_item_label.setText('No selection')
        self._widget.publishers_list.clear()
        self._widget.subscribers_list.clear()
        self._widget.publishers_header.setText('Publishers:')
        self._widget.subscribers_header.setText('Subscribers:')

    def _on_list_item_double_clicked(self, item):
        """Handle double-click on connection list item to focus on it."""
        text = item.text()
        # Remove type annotation if present (e.g., "/topic [std_msgs/String]")
        name = text.split(' [')[0].strip()

        # Determine if it's a topic or node based on current focus type
        if self._focused_item_type == 'node':
            # When a node is focused, list items are topics
            self._focused_item = name
            self._focused_item_type = 'topic'
        else:
            # When a topic is focused, list items are nodes
            self._focused_item = name
            self._focused_item_type = 'node'

        self._refresh_rosgraph()
        self._update_connection_list()
