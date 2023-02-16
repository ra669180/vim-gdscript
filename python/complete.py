import vim
import re
import os

try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

# Flags for selecting which completion items to add.
# There are probably better ways to do this but I'm lazy.
MEMBERS = 1
CONSTANTS = 2
METHODS = 4

# A "token" in this context is something that produces a value, like a
# variable or method. Tokens can be chained via dot accessors.
# Example:
# self.texture.get_size()
# 'self', 'texture', and 'get_size' (without parentheses) are all tokens.
class Token:
    name = None
    type = None

# Token types
TOKEN_MEMBER = 1
TOKEN_METHOD = 2
# Special tokens that can only appear at the beginning of a token chain.
TOKEN_SUPER_ACCESSOR = 3
TOKEN_SUPER_METHOD = 4
TOKEN_STRING_LITERAL = 5

classes = GodotClasses()

def gdscript_complete():
    base = vim.eval("a:base")
    completions = []

    # Only consider the part of the line before the cursor.
    col = get_col() - 1
    line = get_line()[0:col]

    syn_attr = get_syn_attr()
    if syn_attr == "gdComment":
        # Don't complete in comments
        return
    elif syn_attr == "gdString":
        # Complete file paths (res://) if cursor is in a string.
        complete_paths(completions, line)
    elif re.match("(\s*class\s+\w+\s+)?extends\s*", line):
        # Complete class names after 'extends', excluding built-in types.
        complete_class_names(completions, False)
    elif re.match("export\(\s*", line):
        # Complete all class names after 'export'
        complete_class_names(completions)
    elif line and line[-1] == ".":
        # When accessing a value via dot notation, try to guess the type of the
        # value preceding the dot. This works recursively, so chaining dot
        # accessors works as expected if all the intermediary values are
        # built-in members or methods.
        complete_dot(completions, line)
    elif re.match("\s*func", line):
        # Complete functions belonging to the extended type if the cursor is
        # preceded by the 'func' keyword. In this context, the user might be
        # trying to override a built-in function, so the entire function
        # signature is completed including args.
        complete_funcs_with_args(completions, get_extended_class())
    else:
        # Complete members/methods of the extended type as well as
        # global scope and user-defined vars/methods.
        complete_global(completions)

    # Take into account the user's case sensitivity settings.
    ignorecase = int(vim.eval("&ignorecase"))
    smartcase = int(vim.eval("&smartcase"))
    flags = 0
    if ignorecase and (not smartcase or not any(x.isupper() for x in base)):
        flags = re.I

    # Filter completions
    if base:
        completions = [c for c in completions if re.match(base, c["word"], flags)]

    for completion in completions:
        completion["icase"] = int(flags & re.I)

    vim.command("let gdscript_completions = " + str(completions))

def add_class_completions(completions, c, flags):
    def map_fun(x):
        return x.get_completion()

    if not c:
        return

    if flags & MEMBERS:
        completions.extend(map(map_fun, c.iter_members()))
    if flags & CONSTANTS:
        completions.extend(map(map_fun, c.iter_constants()))
    if flags & METHODS:
        completions.extend(map(map_fun, c.iter_methods()))

    add_class_completions(completions, c.get_parent(), flags)

def complete_paths(completions, line):
    m = re.search("res://(((\w|-)+/)*)$", line)
    if m:
        project_dir = get_project_dir()
        if not project_dir:
            return
        subdir = m.group(1)
        # Directories and files are grouped and sorted separately.
        dirs = []
        files = []
        dir = "{}/{}".format(project_dir, subdir)
        if not os.path.isdir(dir):
            return
        for entry in os.listdir(dir):
            if not entry.startswith("."):
                if os.path.isdir("{}/{}".format(dir, entry)):
                    dirs.append({
                        "word": entry,
                        "abbr": "{}/".format(entry),
                        "dup": 1,
                    })
                else:
                    files.append({
                        "word": entry,
                        "dup": 1,
                    })
        dirs.sort(key=lambda c: c["word"])
        files.sort(key=lambda c: c["word"])
        for d in dirs:
            completions.append(d)
        for f in files:
            completions.append(f)

def complete_class_names(completions, built_in=True):
    def filter_fun(c_name):
        return built_in or not classes.is_built_in(c_name)
    def map_fun(c_name):
        return {"word": c_name, "dup": 1}
    filtered = filter(filter_fun, classes.iter_class_names())
    completions.extend(map(map_fun, filtered))

def complete_self(completions):
    c = get_extended_class()
    complete_user(completions)
    add_class_completions(completions, c, MEMBERS | METHODS)

# Helper functions for retrieving members/methods from the
# extended class OR the global scope.

def get_global_member(c, name):
    if not c:
        return
    member = c.get_member(name)
    if not member:
        member = classes.get_global_scope().get_member(name)
    return member

def get_global_method(c, name):
    if not c:
        return
    method = c.get_method(name)
    if not method:
        method = classes.get_global_scope().get_method(name)
    return method


# Try to figure out the type of the last token in a token chain.
# Returns (GodotClass, [completion flags])
def get_preceding_type(completions, tokens):
    if not tokens:
        return None
    c = None
    flags = MEMBERS | METHODS

    # Figure out the type of the first token.
    t = tokens[0]
    if t.type == TOKEN_STRING_LITERAL:
        c = classes.get_class("String")
    # "super accessor" just means a lone dot.
    elif t.type == TOKEN_SUPER_ACCESSOR:
        flags = METHODS
        c = get_extended_class()
    # Super methods are method calls that begin with a dot.
    elif t.type == TOKEN_SUPER_METHOD:
        c_name = get_extended_class().get_method(t.name).get_name()
        c = classes.get_class(c_name)
    # 'self' keyword
    elif t.type == TOKEN_MEMBER and t.name == "self":
        c = get_extended_class()
    else:
        if t.type == TOKEN_MEMBER:
            member = get_global_member(get_extended_class(), t.name)
            if member:
                c = classes.get_class(member.get_type())
            # Statically access class
            elif classes.is_class(t.name):
                flags = CONSTANTS
                c = classes.get_class(t.name)
                # Every non-built-in class has an implicit static 'new()' method.
                # This method doesn't appear in the docs, and is the only static
                # method that I know of, so it's a little tricky to handle.
                if not c.is_built_in():
                    if len(tokens) > 1:
                        if tokens[1].type == TOKEN_METHOD  and tokens[1].name == "new":
                            flags = MEMBERS | METHODS
                            c = classes.get_class(t.name)
                            del tokens[1]
                    elif completions:
                        completions.append({
                            "word": "new()",
                            "abbr": "{}.new()".format(c.get_name()),
                            "kind": "{}".format(c.get_name()),
                        })
        elif t.type == TOKEN_METHOD:
            method = get_global_method(get_extended_class(), t.name)
            if method:
                c = classes.get_class(method.get_return_type())
    del tokens[0]
    if not c:
        return

    # Figure out the types of the remaining tokens
    for token in tokens:
        if token.type == TOKEN_MEMBER:
            member = c.get_member(token.name)
            if member:
                c = classes.get_class(member.get_type())
            else:
                return
        elif token.type == TOKEN_METHOD:
            method = c.get_method(token.name)
            if method:
                c = classes.get_class(method.get_return_type())
            else:
                return
        else:
            # Something is probably seriously wrong if we get to this point.
            return
        if not c:
            return
    return (c, flags)

def complete_dot(completions, line):
    tokens = get_token_chain(line, get_col() - 1)
    (c, flags) = get_preceding_type(completions, tokens) or (None, None)
    if c:
        add_class_completions(completions, c, flags)

def complete_funcs_with_args(completions, c):
    def map_fun(f):
        return f.get_completion_with_args()
    if c:
        completions.extend(map(map_fun, c.iter_methods()))
        complete_funcs_with_args(completions, c.get_parent())


def complete_global(completions):
    c = get_extended_class()
    flags = MEMBERS | CONSTANTS | METHODS
    complete_user(completions)
    add_class_completions(completions, c, flags)
    add_class_completions(completions, classes.get_global_scope(), flags)
    complete_class_names(completions)

# Gather user-defined vars and funcs.
# Only items accessible from the current scope are added.
def complete_user(completions):
    line = get_line()[0:get_col()-1]
    lnum = int(vim.eval("line('.')"))
    if line.lstrip():
        indent = int(vim.eval("indent({})".format(lnum)))
    else:
        # Remember that only the part of the line up to the cursor is considered.
        # If that part of the line is empty, but the entire line is not, vim's
        # indent() function will not return the desired result.
        # In this case, the cursor pos is used instead.
        indent = get_col() - 1

    # Ignore all function arguments after the first encountered function.
    found_func = False
    for prev_lnum in reversed(range(lnum)):
        line = vim.eval("getline({})".format(prev_lnum)).lstrip()
        if not line:
            continue
        prev_indent = int(vim.eval("indent({})".format(prev_lnum)))
        if prev_indent > indent:
            continue
        m = re.match("(?:static\s+)?func\s+(\w+)\(((\w|,|\s)*)\)", line)
        if m:
            if not found_func and indent > prev_indent:
                found_func = True
                for group in m.group(2).split(","):
                    completions.append({"word": group.strip(), "kind": "(local arg)"})
            completions.append({
                "word": "{}(".format(m.group(1)),
                "abbr": "{}({})".format(m.group(1), m.group(2)),
                "kind": "(local func)"
            })
            indent = prev_indent
        elif re.match("^class\s+\w+", line) and prev_indent < indent:
            return
        elif line.startswith("var") or line.startswith("const"):
            m = re.match("(var|const)\s(\w+)", line)
            if m:
                completions.append({"word": m.group(2), "kind": "(local {})".format(m.group(1))})


def is_token_char(char):
    return char.isalnum() or char == "_"

def get_token(line, start):
    paren_count = 0
    is_method = False
    i = start
    end = None
    while True:
        i -= 1
        char = line[i]
        if char == ")":
            is_method = True
            paren_count += 1
        elif char == "(":
            paren_count -= 1
            if paren_count == 0:
                start = i
                continue
        if paren_count <= 0 and not is_token_char(char):
            end = i + 1
            break
        elif i == 0:
            end = i
            break
    token = Token()
    token.name = line[end:start]
    if not token.name:
        if get_syn_attr(col=i+1) == "gdString":
            token.type = TOKEN_STRING_LITERAL
        else:
            token.type = TOKEN_SUPER_ACCESSOR
    elif is_method:
        token.type = TOKEN_METHOD
    else:
        token.type = TOKEN_MEMBER
    return (token, i)

def get_token_chain(line, start_col):
    tokens = []
    i = start_col - 1
    while i > 0 and line[i] == ".":
        (token, i) = get_token(line, i)
        tokens.append(token)
    if len(tokens) == 0:
        return
    tokens.reverse()
    # Combine first two tokens if they result in a super method accessor.
    if tokens[0].type == TOKEN_SUPER_ACCESSOR:
        if len(tokens) > 1:
            if tokens[1].type == TOKEN_METHOD:
                tokens[1].type = TOKEN_SUPER_METHOD
                del tokens[0]
            else:
                # Super accessor followed by a non-method is invalid.
                return None
    return tokens

def get_extended_class():
    # Check if the current function is part of an inner class.
    # If it is, return the extended class of the inner class.
    lnum = int(vim.eval("line('.')"))
    found_func = False
    for i in range(lnum, 0, -1):
        line = vim.eval("getline({})".format(i))
        if not line.strip():
            continue
        if not found_func:
            # Search upwards for 'func'.
            if re.match("\s*func\s+", line):
                # If the line is indented, it means the func is part of an inner class.
                # In this case, start searching for the inner class.
                if int(vim.eval("indent({})".format(i))) > 0:
                    found_func = True
                else:
                    break
        else:
            # Search for the inner class that holds the current function
            m = re.match("class\s+\w*\s+extends\s+(\w+)", line)
            if m:
                return classes.get_class(m.group(1))

    # No inner class, so return the script's extended class

    # Search for 'extends' statement starting from the top.
    for i in range(1, int(vim.eval("line('$')"))):
        line = vim.eval("getline({})".format(i))
        if not line.strip():
            continue
        m = re.match("^extends\s+(\w+)", line)
        if m:
            return classes.get_class(m.group(1))
        elif not re.match("^\s*tool\s*$", line):
            # Give up when encountering a line that isn't 'extends' or 'tool'.
            return None

def get_line():
    return vim.eval("getline('.')")


def get_col():
    return int(vim.eval("col('.')"))

def get_syn_attr(line=None, col=None):
    if not line:
        line = "line('.')"
    if not col:
        col = "col('.')-1"
    return vim.eval("synIDattr(synID({}, {}, 1), 'name')".  format(line, col))


# Get the root directory of the Godot project containing the current script.
# This is for completing 'res://'
_project_dir = None
def get_project_dir():
    global _project_dir
    if not _project_dir:
        cwd = os.getcwd()
        os.chdir(vim.eval("expand('%:p:h')")) # Directory of current file.
        try:
            while not os.path.isfile("project.godot"):
                os.chdir("..")
                if os.getcwd() == "/":
                    return
            _project_dir = os.getcwd()
        except:
            pass
        finally:
            os.chdir(cwd)
    return _project_dir



# echodoc

_hl_identifier = ""
_hl_arguments = ""

def echodoc_search():
    text = vim.eval("a:text")
    text_len = len(text)
    if text_len == 0:
        return
    line = get_line()[0:get_col() - text_len - 1]
    tokens = get_token_chain(line, len(line))

    if not tokens or len(tokens) == 0:
        c = get_extended_class()
        global_method = True
    else:
        (c, _) = get_preceding_type(None, tokens) or (None, None)
        global_method = False

    if not c:
        return

    m = re.match("\w+", text)
    if not m:
        return
    if global_method:
        method = get_global_method(c, m.group(0))
    else:
        method = c.get_method(m.group(0))

    if not method:
        return

    hl_identifier = vim.eval("g:echodoc#highlight_identifier")
    hl_arguments = vim.eval("g:echodoc#highlight_arguments")
    arg_hl_index = 0
    paren_count = 0
    for char in text[len(m.group(0))+1:]:
        if char == "(":
            paren_count += 1
        elif char == ")":
            paren_count -= 1
        elif char == "," and paren_count <= 0:
            arg_hl_index += 1

    echodoc = [
            { "text": method.get_name(), "highlight": hl_identifier },
            { "text": "(" }
            ]
    arg_count = method.get_arg_count();
    for (i, arg) in enumerate(method.iter_args()):
        d = {"text": "{} {}".format(arg.get_type(), arg.get_name())}
        if arg_hl_index == i:
            d["highlight"] = hl_arguments
        echodoc.append(d)
        if arg_count - 1 > i:
            echodoc.append({"text": ", "})
    echodoc.append({"text": ")"})
    vim.command("let echodoc_search_result = {}".format(str(echodoc)))

