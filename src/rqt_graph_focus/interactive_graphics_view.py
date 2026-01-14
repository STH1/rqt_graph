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
import logging

from python_qt_binding.QtCore import QPointF, QRectF, Qt, Signal
from python_qt_binding.QtGui import QTransform
from python_qt_binding.QtWidgets import QGraphicsView

# Threshold in pixels to distinguish click from drag
CLICK_THRESHOLD = 5

# Module logger
_logger = logging.getLogger('rqt_graph_focus.interactive_graphics_view')


class InteractiveGraphicsView(QGraphicsView):

    # Signal emitted when an item is clicked (not dragged)
    item_clicked = Signal(str)

    def __init__(self, parent=None):
        super(InteractiveGraphicsView, self).__init__(parent)
        self.setObjectName('InteractiveGraphicsView')
        _logger.debug('InteractiveGraphicsView initialized')

        self._last_pan_point = None
        self._last_scene_center = None
        self._press_pos = None

    def mousePressEvent(self, mouse_event):
        self._press_pos = mouse_event.pos()
        self._last_pan_point = mouse_event.pos()
        self._last_scene_center = self._map_to_scene_f(QRectF(self.frameRect()).center())
        self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, mouse_event):
        # Check if this was a click (minimal movement) vs a drag
        if self._press_pos is not None:
            delta = mouse_event.pos() - self._press_pos
            if delta.manhattanLength() < CLICK_THRESHOLD:
                # This was a click - find item at position
                scene_pos = self.mapToScene(mouse_event.pos())
                url = self._find_url_at_position(scene_pos)
                if url:
                    self.item_clicked.emit(url)

        self.setCursor(Qt.OpenHandCursor)
        self._last_pan_point = None
        self._press_pos = None

    def _find_url_at_position(self, scene_pos):
        """Find URL from any item at the given scene position."""
        scene = self.scene()
        if not scene:
            _logger.debug('No scene available')
            return None

        # Get all items at this position
        items = scene.items(scene_pos)
        _logger.debug(f'Found {len(items)} items at position {scene_pos}')

        # Search through all items and their parents for a URL
        for item in items:
            url = self._extract_url_from_item(item)
            if url:
                _logger.info(f'Found URL: {url}')
                return url
        _logger.debug('No URL found in any item')
        return None

    def _extract_url_from_item(self, item):
        """Extract URL from a graphics item or its parents."""
        current = item
        visited = set()

        while current and id(current) not in visited:
            visited.add(id(current))

            # Try toolTip (qt_dotgraph stores URL there)
            tooltip = current.toolTip()
            if tooltip and self._is_valid_url(tooltip):
                return self._clean_url(tooltip)

            # Try data role (some implementations store URL in data)
            try:
                data = current.data(0)
                if data and isinstance(data, str) and self._is_valid_url(data):
                    return self._clean_url(data)
            except (TypeError, AttributeError):
                pass

            # Try parent item
            current = current.parentItem()

        return None

    def _clean_url(self, text):
        """Clean URL by removing surrounding quotes."""
        return text.strip('"\'') if text else text

    def _is_valid_url(self, text):
        """Check if text looks like a valid node/topic URL."""
        if not text:
            return False
        # Node URLs start with '/' or topic URLs start with 'topic:'
        # Exclude multi-line tooltips (e.g. formatted node info)
        # but allow HTML-formatted tooltips (which use <br/> not \n)
        if '\n' in text:
            return False
        # Check for valid URL patterns
        # Strip any surrounding quotes that pydot might add
        clean_text = text.strip('"\'')
        return clean_text.startswith('/') or clean_text.startswith('topic:')

    def mouseMoveEvent(self, mouse_event):
        if self._last_pan_point is not None:
            delta_scene = self.mapToScene(mouse_event.pos()) - self.mapToScene(self._last_pan_point)
            if not delta_scene.isNull():
                self.centerOn(self._last_scene_center - delta_scene)
                self._last_scene_center -= delta_scene
            self._last_pan_point = mouse_event.pos()
        QGraphicsView.mouseMoveEvent(self, mouse_event)

    def wheelEvent(self, wheel_event):
        if wheel_event.modifiers() == Qt.NoModifier:
            try:
                delta = wheel_event.angleDelta().y()
            except AttributeError:
                delta = wheel_event.delta()
            delta = max(min(delta, 480), -480)
            mouse_before_scale_in_scene = self.mapToScene(wheel_event.pos())

            scale_factor = 1 + (0.2 * (delta / 120.0))
            scaling = QTransform(scale_factor, 0, 0, scale_factor, 0, 0)
            self.setTransform(self.transform() * scaling)

            mouse_after_scale_in_scene = self.mapToScene(wheel_event.pos())
            center_in_scene = self.mapToScene(self.frameRect().center())
            self.centerOn(
                center_in_scene + mouse_before_scale_in_scene - mouse_after_scale_in_scene)

            wheel_event.accept()
        else:
            QGraphicsView.wheelEvent(self, wheel_event)

    def _map_to_scene_f(self, pointf):
        point = pointf.toPoint()
        if pointf.x() == point.x() and pointf.y() == point.y():
            # map integer coordinates
            return self.mapToScene(point)
        elif pointf.x() == point.x():
            # map integer x and decimal y coordinates
            pointA = self.mapToScene((pointf + QPointF(0, -0.5)).toPoint())
            pointB = self.mapToScene((pointf + QPointF(0, 0.5)).toPoint())
            return (pointA + pointB) / 2.0
        elif pointf.y() == point.y():
            # map decimal x  and integer y and coordinates
            pointA = self.mapToScene((pointf + QPointF(-0.5, 0)).toPoint())
            pointB = self.mapToScene((pointf + QPointF(0.5, 0)).toPoint())
            return (pointA + pointB) / 2.0
        else:
            # map decimal coordinates
            pointA = self.mapToScene((pointf + QPointF(-0.5, -0.5)).toPoint())
            pointB = self.mapToScene((pointf + QPointF(-0.5, 0.5)).toPoint())
            pointC = self.mapToScene((pointf + QPointF(0.5, -0.5)).toPoint())
            pointD = self.mapToScene((pointf + QPointF(0.5, 0.5)).toPoint())
            return (pointA + pointB + pointC + pointD) / 4.0
