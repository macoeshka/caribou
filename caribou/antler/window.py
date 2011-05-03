# -*- coding: utf-8 -*-
#
# Caribou - text entry and UI navigation application
#
# Copyright (C) 2009 Eitan Isaacson <eitan@monotonous.org>
# Copyright (C) 2010 Warp Networks S.L.
#  * Contributor: Daniel Baeyens <dbaeyens@warp.es>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation; either version 2.1 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License
# for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Clutter
import os
import sys
import gobject

Clutter.init("antler")

class ProximityWindowBase(object):
    def __init__(self, min_alpha=1.0, max_alpha=1.0, max_distance=100):
        if self.__class__ == ProximityWindowBase:
            raise TypeError, \
                "ProximityWindowBase is an abstract class, " \
                "must be subclassed with a Gtk.Window"
        self.connect('map-event', self.__onmapped)
        self.max_distance = max_distance
        if max_alpha < min_alpha:
            raise ValueError, "min_alpha can't be larger than max_alpha"
        self.min_alpha = min_alpha
        self.max_alpha = max_alpha

    def __onmapped(self, obj, event):
        if self.is_composited():
            self.set_opacity(self.max_alpha)
            if self.max_alpha != self.min_alpha:
                # Don't waste CPU if the max and min are equal.
                glib.timeout_add(80, self._proximity_check)

    def _proximity_check(self):
        px, py = self.get_pointer()

        ww = self.get_allocated_width()
        wh = self.get_allocated_height()

        distance =  self._get_distance_to_bbox(px, py, ww, wh)

        opacity = (self.max_alpha - self.min_alpha) * \
            (1 - min(distance, self.max_distance)/self.max_distance)
        opacity += self.min_alpha

        self.set_opacity(opacity)
        return self.props.visible

    def _get_distance_to_bbox(self, px, py, bw, bh):
        if px < 0:
            x_distance = float(abs(px))
        elif px > bw:
            x_distance = float(px - bw)
        else:
            x_distance = 0.0

        if py < 0:
            y_distance = float(abs(px))
        elif py > bh:
            y_distance = float(py - bh)
        else:
            y_distance = 0.0

        if y_distance == 0 and x_distance == 0:
            return 0.0
        elif y_distance != 0 and x_distance == 0:
            return y_distance
        elif y_distance == 0 and x_distance != 0:
            return x_distance
        else:
            x2 = 0 if x_distance > 0 else bw
            y2 = 0 if y_distance > 0 else bh
            return sqrt((px - x2)**2 + (py - y2)**2)

class AntlerWindow(Gtk.Window, Clutter.Animatable, ProximityWindowBase):
    __gtype_name__ = "AntlerWindow"
    __gproperties__ = { 
        'animated-window-position' : (gobject.TYPE_PYOBJECT, 'Window position',
                                      'Window position in X, Y coordinates',
                                      gobject.PARAM_READWRITE)        
        }

    def __init__(self, text_entry_mech, default_placement=None,
                 min_alpha=1.0, max_alpha=1.0, max_distance=100,
                 animation_mode=Clutter.AnimationMode.EASE_IN_QUAD):
        gobject.GObject.__init__(self, type=Gtk.WindowType.POPUP)
        ProximityWindowBase.__init__(self,
                                     min_alpha=min_alpha,
                                     max_alpha=max_alpha,
                                     max_distance=max_distance)

        self.set_name("AntlerWindow")

        self._vbox = Gtk.VBox()
        self.add(self._vbox)
        self.keyboard = text_entry_mech
        self._vbox.pack_start(text_entry_mech, True, True, 0)

        self.connect("size-allocate", lambda w, a: self._update_position())

        self._cursor_location = Rectangle()
        self._entry_location = Rectangle()
        self._default_placement = default_placement or \
            AntlerWindowPlacement()

        self.connect('show', self._on_window_show)

        # animation
        self.animation_mode = animation_mode
        self._stage = Clutter.Stage.get_default()
        self._animation = None

    def do_get_property(self, property):
        if property.name == "animated-window-position":
            return self.get_position()
        else:
            raise AttributeError, 'unknown property %s' % property.name

    def do_set_property(self, property, value):
        if property.name == "animated-window-position":
            if value is not None:
                x, y = value
                self.move(x, y)
        else:
            raise AttributeError, 'unknown property %s' % property.name

    def do_animate_property(self, animation, prop_name, initial_value,
                            final_value, progress, gvalue):
        if prop_name != "animated-window-position": return False
        
        ix, iy = initial_value
        fx, fy = final_value
        dx = int((fx - ix) * progress)
        dy = int((fy - iy) * progress)
        new_value = (ix + dx, iy + dy)
        self.move(*new_value)
        return True

    def animated_move(self, x, y):
        self._animation = Clutter.Animation(object=self,
                                            mode=self.animation_mode,
                                            duration=250)
        self._animation.bind("animated-window-position", (x, y))

        timeline = self._animation.get_timeline()
        timeline.start()

        return self._animation

    def destroy(self):
        self.keyboard.destroy()
        super(Gtk.Window, self).destroy()

    def set_cursor_location(self, x, y, w, h):
        self._cursor_location = Rectangle(x, y, w, h)
        self._update_position()

    def set_entry_location(self, x, y, w, h):
        self._entry_location = Rectangle(x, y, w, h)
        self._update_position()

    def set_default_placement(self, default_placement):
        self._default_placement = default_placement
        self._update_position()

    def _get_root_bbox(self):
        root_window = Gdk.get_default_root_window()
        args = root_window.get_geometry()

        root_bbox = Rectangle(*args)

        # TODO: Do whatever we need to do to place the keyboard correctly
        # in GNOME Shell and Unity.
        #
        #current_screen = Gdk.Screen.get_default().get_number()
        #for panel in self._gconf_client.all_dirs('/apps/panel/toplevels'):
        #    orientation = self._gconf_client.get_string(panel+'/orientation')
        #    size = self._gconf_client.get_int(panel+'/size')
        #    screen = self._gconf_client.get_int(panel+'/screen')
        #    if screen != current_screen:
        #        continue
        #    if orientation == 'top':
        #        root_bbox.y += size
        #        root_bbox.height -= size
        #    elif orientation == 'bottom':
        #        root_bbox.height -= size
        #    elif orientation == 'right':
        #        root_bbox.x += size
        #        root_bbox.width -= size
        #    elif orientation == 'left':
        #        root_bbox.x -= size
        
        return root_bbox

    def _calculate_position(self, placement=None):
        root_bbox = self._get_root_bbox()
        placement = placement or self._default_placement

        x = self._calculate_axis(placement.x, root_bbox)
        y = self._calculate_axis(placement.y, root_bbox)

        return x, y

    def _update_position(self):
        x, y = self._calculate_position()
        root_bbox = self._get_root_bbox()
        proposed_position = Rectangle(x, y, self.get_allocated_width(),
                                      self.get_allocated_height())
        
        x += self._default_placement.x.adjust_to_bounds(root_bbox, proposed_position)
        y += self._default_placement.y.adjust_to_bounds(root_bbox, proposed_position)
        self.move(x, y)

    def _calculate_axis(self, axis_placement, root_bbox):
        bbox = root_bbox

        if axis_placement.stickto == AntlerWindowPlacement.CURSOR:
            bbox = self._cursor_location
        elif axis_placement.stickto == AntlerWindowPlacement.ENTRY:
            bbox = self._entry_location

        offset = axis_placement.get_offset(bbox.x, bbox.y)

        if axis_placement.align == AntlerWindowPlacement.END:
            offset += axis_placement.get_length(bbox.width, bbox.height)
            if axis_placement.gravitate == AntlerWindowPlacement.INSIDE:
                offset -= axis_placement.get_length(
                    self.get_allocated_width(),
                    self.get_allocated_height())
        elif axis_placement.align == AntlerWindowPlacement.START:
            if axis_placement.gravitate == AntlerWindowPlacement.OUTSIDE:
                offset -= axis_placement.get_length(
                    self.get_allocated_width(),
                    self.get_allocated_height())
        elif axis_placement.align == AntlerWindowPlacement.CENTER:
            offset += axis_placement.get_length(bbox.width, bbox.height)/2

        return offset

    def show_all(self):
        Gtk.Window.show_all(self)
        self.keyboard.show_all()

    def hide(self):
        self.keyboard.hide()
        Gtk.Window.hide(self)

    def _on_window_show(self, window):
        child = self.get_child()
        border = self.get_border_width()
        req = child.size_request()
        self.resize(req.width + border, req.height + border)

class AntlerWindowDocked(AntlerWindow):
    __gtype_name__ = "AntlerWindowDocked"
    
    def __init__(self, text_entry_mech):
        placement = AntlerWindowPlacement(
            xalign=AntlerWindowPlacement.END,
            yalign=AntlerWindowPlacement.START,
            xstickto=AntlerWindowPlacement.SCREEN,
            ystickto=AntlerWindowPlacement.SCREEN,
            xgravitate=AntlerWindowPlacement.INSIDE)

        AntlerWindow.__init__(self, text_entry_mech, placement)

        self.connect('map-event', self.__onmapped)

    def __onmapped(self, obj, event):
        self._roll_in()

    def _roll_in(self):
        x, y = self.get_position()
        self.move(x + self.get_allocated_width(), y)
        return self.animated_move(x, y)

    def _roll_out(self):
        x, y = self.get_position()
        return self.animated_move(x + self.get_allocated_width(), y)

    def hide(self):
        animation = self._roll_out()
        animation.connect('completed', lambda x: AntlerWindow.hide(self)) 

class AntlerWindowEntry(AntlerWindow):
    __gtype_name__ = "AntlerWindowEntry"

    def __init__(self, text_entry_mech):
        placement = AntlerWindowPlacement(
            xalign=AntlerWindowPlacement.START,
            xstickto=AntlerWindowPlacement.ENTRY,
            ystickto=AntlerWindowPlacement.ENTRY,
            xgravitate=AntlerWindowPlacement.INSIDE,
            ygravitate=AntlerWindowPlacement.OUTSIDE)

        AntlerWindow.__init__(self, text_entry_mech, placement)


    def _calculate_axis(self, axis_placement, root_bbox):
        offset = AntlerWindow._calculate_axis(self, axis_placement, root_bbox)
        if axis_placement.axis == 'y':
            if offset + self.get_allocated_height() > root_bbox.height + root_bbox.y:
                new_axis_placement = axis_placement.copy(align=AntlerWindowPlacement.START)
                offset = AntlerWindow._calculate_axis(self, new_axis_placement, root_bbox)

        return offset

class AntlerWindowPlacement(object):
    START = 'start'
    END = 'end'
    CENTER = 'center'

    SCREEN = 'screen'
    ENTRY = 'entry'
    CURSOR = 'cursor'

    INSIDE = 'inside'
    OUTSIDE = 'outside'

    class _AxisPlacement(object):
        def __init__(self, axis, align, stickto, gravitate):
            self.axis = axis
            self.align = align
            self.stickto = stickto
            self.gravitate = gravitate

        def copy(self, align=None, stickto=None, gravitate=None):
            return self.__class__(self.axis,
                                  align or self.align,
                                  stickto or self.stickto,
                                  gravitate or self.gravitate)

        def get_offset(self, x, y):
            return x if self.axis == 'x' else y

        def get_length(self, width, height):
            return width if self.axis == 'x' else height

        def adjust_to_bounds(self, root_bbox, child_bbox):
            child_vector_start = self.get_offset(child_bbox.x, child_bbox.y)
            child_vector_end = \
                self.get_length(child_bbox.width, child_bbox.height) + \
                child_vector_start
            root_vector_start = self.get_offset(root_bbox.x, root_bbox.y)
            root_vector_end = self.get_length(
                root_bbox.width, root_bbox.height) + root_vector_start

            if root_vector_end < child_vector_end:
                return root_vector_end - child_vector_end

            if root_vector_start > child_vector_start:
                return root_vector_start - child_vector_start

            return 0


    def __init__(self,
                 xalign=None, xstickto=None, xgravitate=None,
                 yalign=None, ystickto=None, ygravitate=None):
        self.x = self._AxisPlacement('x',
                                     xalign or self.END,
                                     xstickto or self.CURSOR,
                                     xgravitate or self.OUTSIDE)
        self.y = self._AxisPlacement('y',
                                     yalign or self.END,
                                     ystickto or self.CURSOR,
                                     ygravitate or self.OUTSIDE)

class Rectangle(object):
    def __init__(self, x=0, y=0, width=0, height=0):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

if __name__ == "__main__":
    import keyboard_view
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    w = AntlerWindowDocked(keyboard_view.AntlerKeyboardView())
    w.show_all()

    try:
        Gtk.main()
    except KeyboardInterrupt:
        Gtk.main_quit()