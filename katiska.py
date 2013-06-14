#!/usr/bin/env python3

import os
import signal
import subprocess

from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Vte

class Window(Gtk.Window):

	def __init__(self, name):
		super(Window, self).__init__(title=name)

		self.connect("key-press-event", self.on_window_key_press)

	def on_window_key_press(self, window, event):
		key = Gdk.keyval_name(event.keyval)
		if key == "h":
			self.split_tile(horizontal=True)
		elif key == "v":
			self.split_tile(vertical=True)

class Screen(Window):

	def __init__(self):
		super(Screen, self).__init__("Katiska")

		self.fixed = Gtk.Fixed()
		self.add(self.fixed)

		self.set_decorated(False)
		self.set_resizable(False)
		self.set_keep_below(True)
		self.set_deletable(False)
		self.set_skip_taskbar_hint(True)
		self.set_skip_pager_hint(True)
		self.maximize()

		self.show_all()

		x, y = 0, 0
		w, h = 1920, 1080 - 23

		self.tiles = []
		self.windows = set()

		self.add_tile((x, y), (w // 2, h))
		self.add_tile((x + w // 2, y), (w // 2, h))

	def add_tile(self, *args):
		self.tiles.append(Tile(self, *args))

	def split_tile(self, *args, **kwargs):
		x, y = self.get_pointer()
		tile = self.get_closest_tile(x, y)
		if tile:
			tile.split(*args, **kwargs)

	def get_closest_tile(self, x, y):
		for tile in self.tiles:
			x0, y0 = tile.position
			w, h = tile.size
			x1 = x0 + w
			y1 = y0 + h

			if x >= x0 and x < x1 and y >= y0 and y < y1:
				return tile

		return None

	def reconfigure(self):
		for window in self.windows:
			window.reconfigure()

class Titlebar(object):

	def __init__(self, tile):
		self.tile = tile
		self.height = 20

		x, y = self.tile.position
		w, h = self.tile.size

		self.label = Gtk.Label("<empty>")
		self.label.set_single_line_mode(True)
		self.label.set_size_request(w - 2, self.height - 2)
		self.label.show()

		self.screen.fixed.put(self.label, x + 1, y + 1)

	@property
	def screen(self):
		return self.tile.screen

	def reconfigure(self):
		x, y = self.tile.position
		w, h = self.tile.size

		self.label.set_size_request(w - 2, self.height - 2)
		self.screen.fixed.move(self.label, x + 1, y + 1)

class Tile(object):

	def __init__(self, screen, position, size):
		self.screen = screen
		self.position = position
		self.size = size
		self.titlebar = Titlebar(self)

	@property
	def window_position(self):
		x, y = self.position
		return x + 1, y + self.titlebar.height + 1

	@property
	def window_size(self):
		w, h = self.size
		return w - 2, h - self.titlebar.height - 2

	def split(self, horizontal=False, vertical=False):
		if horizontal:
			w, h = self.size
			w1 = w // 2
			w2 = w - w1

			x, y = self.position
			x2 = x + w1

			self.size = w1, h

			self.screen.add_tile((x2, y), (w2, h))

		if vertical:
			w, h = self.size
			h1 = h // 2
			h2 = h - h1

			x, y = self.position
			y2 = y + h1

			self.size = w, h1

			self.screen.add_tile((x, y2), (w, h2))

		self.titlebar.reconfigure()
		self.screen.reconfigure()

class TiledWindow(Window):

	def __init__(self, name, tile):
		super(TiledWindow, self).__init__(name)

		self.tile = tile

		self.set_decorated(False)
		self.set_default_size(*tile.window_size)
		self.move(*tile.window_position)
		self.connect("destroy", self.on_window_destroy)
		self.connect("configure-event", self.on_window_configure)

		self.screen.windows.add(self)

	@property
	def screen(self):
		return self.tile.screen

	def split_tile(self, *args, **kwargs):
		self.tile.split(*args, **kwargs)

	def on_window_destroy(self, window):
		self.screen.windows.remove(self)

	def on_window_configure(self, window, event):
		x = event.x + event.width // 2
		y = event.y + event.height // 2

		tile = self.screen.get_closest_tile(x, y)
		if tile:
			self.tile = tile
			self._reconfigure((event.x, event.y), (event.width, event.height))

	def reconfigure(self):
		x, y = self.get_position()
		w, h = self.get_size()

		self._reconfigure((x, y), (w, h))

	def _reconfigure(self, position, size):
		if position != self.tile.window_position:
			self.move(*self.tile.window_position)

		if size != self.tile.window_size:
			self.set_size_request(*self.tile.window_size)
			self.resize(*self.tile.window_size)

class Terminal(TiledWindow):

	def __init__(self, tile):
		super(Terminal, self).__init__("Terminal", tile)

		workdir = os.environ["HOME"]
		shell = os.environ.get("SHELL", "/bin/bash")

		self.terminal = Vte.Terminal()
		self.terminal.fork_command_full(Vte.PtyFlags.DEFAULT, workdir, [shell], [], 0, None, None)
		self.terminal.connect("destroy", self.on_terminal_destroy)
		self.terminal.connect("child-exited", self.on_child_exited)
		self.add(self.terminal)
		self.show_all()

	def on_terminal_destroy(self, terminal):
		self.destroy()

	def on_child_exited(self, terminal):
		self.destroy()

class EmbeddedWindow(TiledWindow):

	def __init__(self, name, tile):
		super(EmbeddedWindow, self).__init__(name, tile)

		self.proc = None

		self.socket = Gtk.Socket()
		self.socket.set_can_focus(True)
		self.socket.connect_after("map", self.on_socket_map)
		self.socket.connect_after("destroy", self.on_socket_destroy)
		self.add(self.socket)
		self.show_all()

	def on_socket_map(self, socket):
		if not self.proc:
			self.proc = subprocess.Popen(self.get_args(str(socket.get_id())))
			socket.connect("destroy", self.on_socket_destroy)

	def on_socket_destroy(self, socket):
		if self.proc:
			proc = self.proc
			self.proc = None
			proc.terminate()
			proc.wait()

		self.destroy()

class Emacs(EmbeddedWindow):

	def __init__(self, tile):
		super(Emacs, self).__init__("Emacs", tile)

	def get_args(self, xid):
		return ["emacs", "--parent-id", xid]

def main():
	signal.signal(signal.SIGINT, signal.SIG_DFL)
	signal.signal(signal.SIGTERM, signal.SIG_DFL)

	screen = Screen()
	Terminal(screen.tiles[0])
	Emacs(screen.tiles[1])

	Gtk.main()

if __name__ == "__main__":
	main()
