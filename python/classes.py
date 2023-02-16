import vim
import os
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

_DOCS_DIR = vim.eval("expand('<sfile>:p:h')") + "/../python/godot-docs"

_BUILT_IN_TYPES = [
    "AABB", "Array", "Basis", "bool", "Color", "Dictionary", "float",
    "int", "Nil", "NodePath", "Plane", "PoolByteArray", "PoolColorArray",
    "PoolIntArray", "PoolRealArray", "PoolStringArray", "PoolVector2Array",
    "PoolVector3Array", "Quat", "Rect2", "RID", "String", "Transform2D",
    "Transform", "Vector2", "Vector3"
    ]

# Loads and stores Godot class info.
# Everything is loaded on demand, so there's no overhead if completion isn't used.
class GodotClasses:
    _class_names = None
    _classes = {}
    _global_scope = None

    # Gather the names of all classes found in the docs directory.
    def _load_class_names(self):
        if not self._class_names:
            self._class_names = []
            for f in os.listdir(_DOCS_DIR):
                if not f.startswith("@"):
                    name = os.path.splitext(os.path.basename(f))[0]
                    self._class_names.append(name)
                    if not name in self._classes:
                        self._classes[name] = None
            self._class_names.sort()

    def _load_global_scope(self):
        # Global scope is divided between several XML files, so here we
        # hackily combine them into a single "class".
        global_scope = self.get_class("@GlobalScope")
        gdscript = self.get_class("@GDScript")

        global_scope._members.extend(gdscript._members)
        global_scope._constants.extend(gdscript._constants)
        global_scope._methods.extend(gdscript._methods)

        # @GlobalScope doesn't contain any methods, and @GDScript
        # doesn't contain any members. This means only the constants need
        # to be sorted after merging, as the other two will be unchanged.
        global_scope._constants.sort(key=lambda c: c.get_name())

        global_scope._members_lookup.update(gdscript._members_lookup)
        global_scope._constants_lookup.update(gdscript._constants_lookup)
        global_scope._methods_lookup.update(gdscript._methods_lookup)

        # Gather constructors. Only built-in types have constructors,
        # e.g. Vector2(). All other types are created via "new()", which for
        # our purposes isn't considered a constructor.
        constructors = []
        for c_name in _BUILT_IN_TYPES:
            path = "{}/{}.xml".format(_DOCS_DIR, c_name)
            current_method = None

            try:
                for event, elem in ET.iterparse(path, events=("start", "end")):
                    attrib = elem.attrib
                    if event == "start":
                        if elem.tag == "method":
                            # Encountered a non-constructor, so stop searching.
                            if attrib["name"] != c_name:
                                break
                            method = GodotMethod(attrib)
                            constructors.append(method)
                            global_scope._methods_lookup[method._name] = method
                            current_method = method
                        elif elem.tag == "argument":
                            current_method._add_arg(attrib)
                        elif elem.tag == "return":
                            current_method._set_return_type(attrib)
                    else:
                        if elem.tag == "method":
                            current_method._finish(c_name)
                        elem.clear()
            except IOError:
                pass

        global_scope._methods.extend(sorted(constructors, key=lambda m: m._name))
        self._global_scope = global_scope

    def get_class(self, c_name):
        if not c_name:
            return None
        c = self._classes.get(c_name)
        if not c:
            try:
                c = GodotClass(c_name, self)
                self._classes[c_name] = c
            except IOError:
                pass
        return c

    # Like GodotClass.is_built_in(), but doesn't require the class to be loaded
    # since built-in types are defined manually.
    def is_built_in(self, c_name):
        return c_name in _BUILT_IN_TYPES

    def get_global_scope(self):
        if not self._global_scope:
            self._load_global_scope()
        return self._global_scope

    def iter_class_names(self):
        self._load_class_names()
        return iter(self._class_names)

    def is_class(self, name):
        self._load_class_names()
        return name in self._classes

class GodotClass:

    # I wrote this whole thing before realizing that a reference to GodotClasses
    # is needed to load parent classes. Passing the reference here is hacky but
    # I don't care.
    def __init__(self, c_name, classes):
        path = "{}/{}.xml".format(_DOCS_DIR, c_name)
        it = ET.iterparse(path, events=("start", "end"))

        self._name = c_name
        self._parent = None
        self._is_built_in = False

        self._members = []
        self._constants = []
        self._methods = []

        # These contain the same items as the above arrays, but are better
        # for getting a particular item by name.
        self._members_lookup = {}
        self._constants_lookup = {}
        self._methods_lookup = {}

        current_method = None
        for event, elem in it:
            if event == "start":
                attrib = elem.attrib
                if elem.tag == "class":
                    if "inherits" in attrib:
                        try:
                            self._parent = classes.get_class(attrib["inherits"])
                        except IOError:
                            pass
                    self._is_built_in = attrib.get("category") == "Built-In Types"
                elif elem.tag == "member":
                    member = GodotMember(attrib, c_name)
                    self._members.append(member)
                    self._members_lookup[member._name] = member
                elif elem.tag == "constant":
                    constant = GodotConstant(attrib, c_name)
                    self._constants.append(constant)
                    self._constants_lookup[constant._name] = constant
                elif elem.tag == "method":
                    # Ignore constuctors as they are handled elsewhere.
                    if attrib["name"] == c_name:
                        current_method = None
                    else:
                        method = GodotMethod(attrib)
                        self._methods.append(method)
                        self._methods_lookup[method._name] = method
                        current_method = method
                elif current_method:
                    if elem.tag == "argument":
                        current_method._add_arg(attrib)
                    elif elem.tag == "return":
                        current_method._set_return_type(attrib)
            else:
                # Method completions can't be built until args and return type
                # are all accounted for.
                if current_method and elem.tag == "method":
                    current_method._finish(c_name)
                elem.clear()

    def get_name(self):
        return self._name

    def get_parent(self):
        return self._parent

    def is_built_in(self):
        return self._is_built_in

    def get_member(self, name, search_parent=True):
        member = self._members_lookup.get(name)
        if not member and search_parent and self._parent:
            return self._parent.get_member(name)
        else:
            return member

    def get_constant(self, name, search_parent=True):
        constant = self._constants_lookup.get(name)
        if not constant and search_parent and self._parent:
            return self._parent.get_constant(name)
        else:
            return constant

    def get_method(self, name, search_parent=True):
        method = self._methods_lookup.get(name)
        if not method and search_parent and self._parent:
            return self._parent.get_method(name)
        else:
            return method

    def iter_members(self):
        return iter(self._members)

    def iter_constants(self):
        return iter(self._constants)

    def iter_methods(self):
        return iter(self._methods)


    # Helper functions for iterating completion items

    def iter_member_completions(self):
        return map(lambda x: x.get_completion(), self._members)

    def iter_constant_completions(self):
        return map(lambda x: x.get_completion(), self._constants)

    def iter_method_completions(self):
        return map(lambda x: x.get_completion(), self._methods)


class GodotMethod:

    def __init__(self, attrib):
        self._name = attrib["name"]
        self._qualifiers = attrib.get("qualifiers", "")
        self._return_type = "void"
        self._args = []

        # Methods have two kinds of completions depending on the context.
        # The first is shown when accessing the method via dot notation.
        # The second is shown when completing after the 'func' keyword.
        self._completion = None
        self._completion_with_args = None

    def _add_arg(self, attrib):
        index = int(attrib.get("index"))
        arg = GodotMethodArg(attrib)

        # This may seem odd, but it ensures the args are ALWAYS in the right order.
        # Granted, there's probably no chance of encountering args out of order,
        # but the XML docs explicitly define indices for each arg, so I might as
        # well take advantage of that.
        while len(self._args) <= index:
            self._args.append(None)
        self._args[index] = arg

    def _set_return_type(self, attrib):
        self._return_type = attrib.get("enum", attrib.get("type", "void"))

    def _finish(self, c_name):
        if c_name.startswith("@") or self._name == c_name:
            name = self._name
        else:
            name = "{}.{}".format(c_name, self._name)
        qualifiers = self._qualifiers if self._qualifiers else ""

        def map_arg(arg):
            default = "={}".format(arg._default) if arg._default else ""
            return "{} {}{}".format(arg._type, arg._name, default)

        # Normal completion
        args = list(map(map_arg, self._args))
        if "vararg" in qualifiers:
            args.append("...")
        self._completion = {
            "word": "{}({}".format(self._name, ")" if len(args) == 0 else ""),
            "abbr": "{}({}) {}".format(name, ", ".join(args), qualifiers),
            "kind": self._return_type,
            "dup": 1,
        }

        # Completion with args
        args = list(map(lambda a: a._name, self._args))
        self._completion_with_args = {
            "word": "{}({}):".format(self._name, ", ".join(args)),
            "abbr": self._completion["abbr"],
            "kind": self._return_type,
            "dup": 1,
        }


    def get_name(self):
        return self._name

    def get_qualifiers(self):
        return self._qualifiers

    def get_return_type(self):
        return self._return_type

    def get_arg(self, index):
        return self._args[index]

    def get_arg_by_name(self, name):
        for arg in self._args:
            if arg._name == name:
                return arg
        return None

    def iter_args(self):
        return iter(self._args)

    def get_arg_count(self):
        return len(self._args)

    def get_completion(self):
        return self._completion

    def get_completion_with_args(self):
        return self._completion_with_args

class GodotMethodArg:

    def __init__(self, attrib):
        self._name = attrib["name"]
        self._type = attrib["type"]
        self._default = attrib.get("default")

    def get_name(self):
        return self._name

    def get_type(self):
        return self._type

    def get_default(self):
        return self._default

class GodotMember:

    def __init__(self, attrib, c_name):
        self._name = attrib["name"]
        self._type = attrib.get("enum", attrib["type"])
        if c_name.startswith("@"):
            abbr = self._name
        else:
            abbr = "{}.{}".format(c_name, self._name)
        self._completion = {
            "word": self._name,
            "abbr": abbr,
            "kind": self._type,
            "dup": 1,
        }

    def get_name(self):
        return self._name

    def get_type(self):
        return self._type

    def get_completion(self):
        return self._completion

class GodotConstant:

    def __init__(self, attrib, c_name):
        self._name = attrib["name"]
        self._type = attrib.get("enum")
        self._value = attrib.get("value")
        if c_name.startswith("@"):
            abbr = self._name
        else:
            abbr = "{}.{}".format(c_name, self._name)
        self._completion = {
            "word": self._name,
            "abbr": abbr,
            "dup": 1,
        }
        if self._type:
            self._completion["kind"] = self._type
        if self._value:
            self._completion["abbr"] += " = {}".format(self._value)

    def get_name(self):
        return self._name

    def get_type(self):
        return self._type

    def get_value(self):
        return self._value

    def get_completion(self):
        return self._completion

