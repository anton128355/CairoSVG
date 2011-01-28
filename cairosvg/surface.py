# -*- coding: utf-8 -*-
# This file is part of CairoSVG
# Copyright © 2010 Kozea
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CairoSVG.  If not, see <http://www.gnu.org/licenses/>.

"""
Cairo surface creator.

"""

# Ignore small variable names here
# pylint: disable=C0103

import abc
import cairo
import io
import os
from math import pi

from .parser import Tree
from .colors import COLORS

# TODO: find a real way to determine DPI
DPI = 72.
UNITS = {
    "mm": DPI / 25.4,
    "cm": DPI / 2.54,
    "in": DPI,
    "pt": DPI / 72.,
    "pc": DPI / 6.,
    "px": 1.,
    "em": NotImplemented,
    "ex": NotImplemented,
    "%": NotImplemented}
ASCII_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def normalize(string=None):
    """Normalize a string corresponding to an array of various vaues."""
    string = string.replace("-", " -")
    string = string.replace(",", " ")

    while "  " in string:
        string = string.replace("  ", " ")

    return string


def size(string=None):
    """Replace a string with units by a float value."""
    if not string:
        return 0

    if string.replace(".", "", 1).lstrip(" -").isdigit():
        return float(string)

    for unit, value in UNITS.items():
        if unit in string:
            return float(string.strip(" " + unit)) * value


def color(string=None, opacity=1):
    """Replace ``string`` representing a color by a RGBA tuple."""
    if not string or string == "none":
        return (0, 0, 0, 0)

    string = string.strip().lower()

    if string in COLORS:
        string = COLORS[string]

    if len(string) in (4, 5):
        string = "#" + "".join(2 * char for char in string[1:])
    if len(string) == 9:
        opacity *= int(string[7:9], 16)/255
    plain_color = tuple(int(value, 16)/255. for value in (
            string[1:3], string[3:5], string[5:7]))
    return plain_color + (opacity,)


def point(string=None):
    """Return ``(x, y, trailing_text)`` from ``string``."""
    if not string:
        return (0, 0, "")

    x, y, string = string.split(" ", 2)
    return size(x), size(y), string


class Surface(object):
    """Cairo abstract surface."""
    # Cairo developers say that there is no way to inherit from cairo.*Surface
    __metaclass__ = abc.ABCMeta

    def __init__(self, tree):
        """Create the surface from ``tree``."""
        width = size(tree.get("width"))
        height = size(tree.get("height"))

        self.bytesio = io.BytesIO()
        self._create_surface(tree, width, height)

        self.draw(tree)

    @abc.abstractmethod
    def _create_surface(self, tree, width, height):
        """Create a cairo surface.

        A method overriding this one must create ``self.cairo`` and
        ``self.context``.

        """
        raise NotImplementedError

    def _set_context_size(self, width, height, viewbox):
        """Set the context size."""
        if viewbox:
            x, y, x_size, y_size = tuple(size(pos) for pos in viewbox.split())
            width = width or x_size
            height = height or y_size
            self.context.scale(width/x_size, height/y_size)
            self.context.translate(-x, -y)

    def read(self):
        """Read the surface content."""
        self.cairo.finish()
        value = self.bytesio.getvalue()
        self.bytesio.close()
        return value

    def draw(self, node):
        """Draw ``node`` and its children."""
        self.context.save()
        self.context.move_to(size(node.get("x")), size(node.get("y")))

        # Transform the context according to the ``transform`` attribute
        if node.get("transform"):
            # TODO: check if multiple-depth transformations work correctly
            transformations = node["transform"].split(")")
            for transformation in transformations:
                for ttype in ("scale", "translate", "matrix"):
                    if ttype in transformation:
                        transformation = transformation.replace(ttype, "")
                        transformation = transformation.replace("(", "")
                        transformation = normalize(transformation).strip() + " "
                        values = []
                        while transformation:
                            value, transformation = transformation.split(" ", 1)
                            values.append(size(value))
                        if ttype == "matrix":
                            matrix = cairo.Matrix(*values)
                            self.context.set_matrix(matrix)
                        else:
                            if len(values) == 1:
                                values = 2 * values
                            getattr(self.context, ttype)(*values)

        # Set drawing informations of the node if the ``node.tag`` method exists
        if hasattr(self, node.tag):
            getattr(self, node.tag)(node)

        # Get stroke and fill opacity
        opacity = float(node.get("opacity", 1))
        stroke_opacity = opacity * float(node.get("stroke-opacity", 1))
        fill_opacity = opacity * float(node.get("fill-opacity", 1))

        # Stroke
        self.context.set_line_width(size(node.get("stroke-width")))
        self.context.set_source_rgba(*color(node.get("stroke"), stroke_opacity))
        self.context.stroke_preserve()

        # Fill
        if node.get("fill-rule") == "evenodd":
            self.context.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        self.context.set_source_rgba(*color(node.get("fill"), fill_opacity))
        self.context.fill()

        # Draw children
        for child in node.children:
            self.draw(child)

        if not node.root:
            # Restoring context is useless if we are in the root tag, it may
            # raise an exception if we have multiple svg tags
            self.context.restore()

    def circle(self, node):
        """Draw a circle ``node``."""
        self.context.arc(
            size(node.get("x")) + size(node.get("cx")),
            size(node.get("y")) + size(node.get("cy")),
            size(node.get("r")), 0, 2*pi)

    def path(self, node):
        """Draw a path ``node``."""
        # Set 1 as default stroke-width
        if not node.get("stroke-width"):
            node["stroke-width"] = "1"

        # Add sentinel
        string = node.get("d", "").strip() + "XX"

        for letter in ASCII_LETTERS:
            string = string.replace(letter, " %s " % letter)

        last_letter = None

        string = normalize(string)
            
        while string:
            string = string.strip()
            if string.split(" ", 1)[0] in ASCII_LETTERS:
                letter, string = string.split(" ", 1)
            if letter == "c":
                # Relative curve
                x1, y1, string = point(string)
                x2, y2, string = point(string)
                x3, y3, string = point(string)
                self.context.rel_curve_to(x1, y1, x2, y2, x3, y3)
            elif letter == "C":
                # Curve
                x1, y1, string = point(string)
                x2, y2, string = point(string)
                x3, y3, string = point(string)
                self.context.curve_to(x1, y1, x2, y2, x3, y3)
            elif letter == "h":
                # Relative horizontal line
                x, string = string.split(" ", 1)
                self.context.rel_line_to(size(x), 0)
            elif letter == "V":
                # Vertical line
                x, string = string.split(" ", 1)
                self.context.line_to(size(x), 0)
            elif letter == "l":
                # Relative straight line
                x, y, string = point(string)
                self.context.rel_line_to(x, y)
            elif letter == "L":
                # Straight line
                x, y, string = point(string)
                self.context.line_to(x, y)
            elif letter == "m":
                # Current point relative move
                x, y, string = point(string)
                self.context.rel_move_to(x, y)
            elif letter == "M":
                # Current point move
                x, y, string = point(string)
                self.context.move_to(x, y)
            elif letter == "S":
                # Smooth curve
                # TODO: manage last_letter in "cs"
                x, y = self.context.get_current_point()
                x1 = x3 - x2 if last_letter in "CS" else x
                y1 = y3 - y2 if last_letter in "CS" else y
                x2, y2, string = point(string)
                x3, y3, string = point(string)
                self.context.curve_to(x1, y1, x2, y2, x3, y3)
            elif letter == "s":
                # Relative smooth curve
                # TODO: manage last_letter in "CS"
                x1 = x3 - x2 if last_letter in "cs" else 0
                y1 = y3 - y2 if last_letter in "cs" else 0
                x2, y2, string = point(string)
                x3, y3, string = point(string)
                self.context.rel_curve_to(x1, y1, x2, y2, x3, y3)
            elif letter == "v":
                # Relative vertical line
                y, string = string.split(" ", 1)
                self.context.rel_line_to(0, size(y))
            elif letter == "V":
                # Vertical line
                y, string = string.split(" ", 1)
                self.context.line_to(0, size(y))
            elif letter == "X":
                # Sentinel: stop
                string = ""
            elif letter.lower() == "z":
                # End of path
                self.context.close_path()
            else:
                # TODO: manage other letters
                raise NotImplementedError

            last_letter = letter

            string = string.strip()

    def line(self, node):
        """Draw a line ``node``."""
        x1, y1, x2, y2 = tuple(size(position) for position in (
                node.get("x1"), node.get("y1"), node.get("x2"), node.get("y2")))
        self.context.move_to(x1, y1)
        self.context.line_to(x2, y2)

    def tspan(self, node):
        x, y = self.cursor_position
        if "x" in node:
            x = size(node["x"])
        if "y" in node:
            y = size(node["y"])
        node["x"] = str(x + size(node.get("dx")))
        node["y"] = str(y + size(node.get("dy")))
        self.text(node)

    def text(self, node):
        """Draw a text ``node``."""
        # Set black as default text color
        if not node.get("fill"):
            node["fill"] = "#000000"

        # TODO: find a better way to do this
        node.text = node.text.strip("\n\r") if node.text else ""

        # TODO: manage font variant
        font_size = size(node.get("font-size", "12pt"))
        font_family = node.get("font-family", "Sans")
        font_style = getattr(
            cairo, ("font_slant_%s" % node.get("font-style")).upper(),
            cairo.FONT_SLANT_NORMAL)
        font_weight = getattr(
            cairo, ("font_weight_%s" % node.get("font-weight")).upper(),
            cairo.FONT_WEIGHT_NORMAL)
        self.context.select_font_face(font_family, font_style, font_weight)
        self.context.set_font_size(font_size)

        # TODO: manage y_bearing and *_advance
        x_bearing, y_bearing, width, height, x_advance, y_advance = \
            self.context.text_extents(node.text)
        x, y = size(node.get("x")), size(node.get("y"))
        text_anchor = node.get("text-anchor")
        if text_anchor == "middle":
            x -= width/2. + x_bearing
        elif text_anchor == "end":
            x -= width + x_bearing
        
        # Get global text opacity
        opacity = float(node.get("opacity", 1))

        self.context.move_to(x, y)
        self.context.set_source_rgba(*color(node.get("fill"), opacity))
        self.context.show_text(node.text)
        self.context.move_to(x, y)
        self.context.text_path(node.text)
        node["fill"] = "#00000000"

        # Remember the cursor position
        self.cursor_position = self.context.get_current_point()

    def use(self, node):
        """Draw the content of another SVG file."""
        self.context.translate(size(node.get("x")), size(node.get("y")))
        if "x" in node:
            del node["x"]
        if "y" in node:
            del node["y"]
        href = node.get("{http://www.w3.org/1999/xlink}href")
        href = os.path.join("/home/lize/Boulot/Kozea/Facturation", href)
        tree = Tree(href, node)
        self._set_context_size(
            size(tree.get("width")), size(tree.get("height")),
            tree.get("viewBox"))
        self.draw(tree)

# pylint: enable=C0103