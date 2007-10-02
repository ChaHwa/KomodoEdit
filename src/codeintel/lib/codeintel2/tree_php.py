#!/usr/bin/env python
# Copyright (c) 2006 ActiveState Software Inc.
# See LICENSE.txt for license details.

"""Completion evaluation code for PHP"""

from codeintel2.common import *
from codeintel2.tree import TreeEvaluator
from codeintel2.util import make_short_name_dict, banner

class PHPTreeEvaluator(TreeEvaluator):
    """
    scoperef: (<blob>, <lpath>) where <lpath> is list of names
        self._elem_from_scoperef()
    hit: (<elem>, <scoperef>)
    """

    # Calltips with this expression value are ignored. See bug:
    # http://bugs.activestate.com/show_bug.cgi?id=61497
    php_ignored_calltip_expressions = ("if", "elseif",
                                       "for", "foreach",
                                       "while",
                                       "switch",
                                      )

    #TODO: candidate for base TreeEvaluator class
    _langintel = None
    @property
    def langintel(self):
        if self._langintel is None:
            self._langintel = self.mgr.langintel_from_lang(self.trg.lang)
        return self._langintel

    #TODO: candidate for base TreeEvaluator class
    _libs = None
    @property
    def libs(self):
        if self._libs is None:
            self._libs = self.langintel.libs_from_buf(self.buf)
        return self._libs

    def eval_cplns(self):
        self.log_start()
        self._imported_blobs = {}
        start_scope = self.get_start_scoperef()
        trg = self.trg
        if trg.type == "variables":
            return self._variables_from_scope(self.expr, start_scope)
        elif trg.type == "functions":
            retval = self._functions_from_scope(self.expr, start_scope)
            #if self.ctlr.is_aborted():
            #    return None
            return retval
        elif trg.type == "classes":
            return self._classes_from_scope(self.expr, start_scope)
        elif trg.type == "interfaces":
            return self._interfaces_from_scope(self.expr, start_scope)
        else:
            hit = self._hit_from_citdl(self.expr, start_scope)
            if hit[0] is not None:
                self.log("self.expr: %r", self.expr)
                # special handling for parent, explicitly set the
                # protected and private member access for this case
                if self.expr == "parent" or \
                   self.expr.startswith("parent."):
                    self.log("Allowing protected parent members")
                    return list(self._members_from_hit(hit, allowProtected=True,
                                                       allowPrivate=False))
                else:
                    return list(self._members_from_hit(hit))

    def eval_calltips(self):
        self.log_start()
        self._imported_blobs = {}
        start_scope = self.get_start_scoperef()
        # Ignore doing a lookup on certain expressions
        # XXX - TODO: Might be better to do this in trg_from_pos.
        if self.expr in self.php_ignored_calltip_expressions:
            return None
        hit = self._hit_from_citdl(self.expr, start_scope)
        return self._calltips_from_hit(hit)

    def eval_defns(self):
        self.log_start()
        self._imported_blobs = {}
        start_scoperef = self.get_start_scoperef()
        self.info("start scope is %r", start_scoperef)

        hit = self._hit_from_citdl(self.expr, start_scoperef, defn_only=True)
        return [self._defn_from_hit(hit)]

    # Determine if the hit is valid
    def _return_with_hit(self, hit, nconsumed):
        # Added special attribute __not_yet_defined__ to the PHP ciler,
        # this is used to indicate the variable was made but is not yet
        # assigned a type, i.e. it's not yet defined.
        elem, scoperef = hit
        attributes = elem.get("attributes")
        if attributes:
            attr_split = attributes.split(" ")
            if "__not_yet_defined__" in attr_split:
                self.log("_return_with_hit:: hit was a not_yet_defined, ignoring it: %r", hit)
                return False
        self.log("_return_with_hit:: hit is okay: %r", hit)
        return True

    def _element_names_from_scope_starting_with_expr(self, expr, scoperef,
                                                     elem_type, scope_names,
                                                     elem_retriever):
        """Return all available elem_type names beginning with expr"""
        self.log("%s_names_from_scope_starting_with_expr:: expr: %r, scoperef: %r for %r",
                 elem_type, expr, scoperef, scope_names)
        global_blob = self._elem_from_scoperef(self._get_global_scoperef(scoperef))
        # Get all of the imports

        # Start making the list of names
        all_names = set()
        for scope_type in scope_names:
            elemlist = []
            if scope_type == "locals":
                elemlist = [self._elem_from_scoperef(scoperef)]
            elif scope_type == "globals":
                elemlist = [global_blob]
            elif scope_type == "builtins":
                lib = self.buf.stdlib
                # Find the matching names (or all names if no expr)
                #log.debug("Include builtins: elem_type: %s", elem_type)
                names = lib.toplevel_cplns(prefix=expr, ilk=elem_type)
                all_names.update([n for ilk,n in names])
            # "Include everything" includes the builtins already
            elif scope_type == "imports":
                # Iterate over all known libs
                for lib in self.libs:
                    # Find the matching names (or all names if no expr)
                    #log.debug("Include everything: elem_type: %s", elem_type)
                    names = lib.toplevel_cplns(prefix=expr, ilk=elem_type)
                    all_names.update([n for ilk,n in names])
                # Standard imports, specified through normal import semantics
                elemlist = self._get_all_import_blobs_for_elem(global_blob)
            for elem in elemlist:
                names = elem_retriever(elem)
                if expr and isinstance(names, dict):
                    try:
                        names = names[expr]
                    except KeyError:
                        # Nothing in the dict matches, thats okay
                        names = []
                self.log("%s_names_from_scope_starting_with_expr:: adding %s: %r",
                         elem_type, scope_type, names)
                all_names.update(names)
        return self._convertListToCitdl(elem_type, all_names)

    def _variables_from_scope(self, expr, scoperef):
        """Return all available variable names beginning with expr"""
        # The current scope determines what is visible, see bug:
        #   http://bugs.activestate.com/show_bug.cgi?id=65159
        blob, lpath = scoperef
        if len(lpath) > 0:
            # Inside a function or class, don't get to see globals
            scope_chain = ("locals", "builtins", )
        else:
            # Already global scope, so get to see them all
            scope_chain = ("locals", "globals", "imports", )
        # XXX - TODO: Move to 3 char trigger (if we want/need to)
        vars = self._element_names_from_scope_starting_with_expr(None,
                            scoperef,
                            "variable",
                            scope_chain,
                            self.variable_names_from_elem)
        # XXX - TODO: Use VARIABLE_TRIGGER_LEN instead of hard coding 1
        expr = expr[:1]
        return [ (ilk, name) for ilk, name in vars if name.startswith(expr) ]

    def _functions_from_scope(self, expr, scoperef):
        """Return all available function names beginning with expr"""
        # XXX - TODO: Use FUNCTION_TRIGGER_LEN instead of hard coding 3
        return self._element_names_from_scope_starting_with_expr(expr[:3],
                            scoperef,
                            "function",
                            ("locals", "globals", "imports",),
                            self.function_shortnames_from_elem)

    def _classes_from_scope(self, expr, scoperef):
        """Return all available class names beginning with expr"""
        return self._element_names_from_scope_starting_with_expr(None,
                            scoperef,
                            "class",
                            ("locals", "globals", "imports",),
                            self.class_names_from_elem)

    def _interfaces_from_scope(self, expr, scoperef):
        """Return all available interface names beginning with expr"""
        # Need to work from the global scope for this one
        return self._element_names_from_scope_starting_with_expr(expr,
                            scoperef,
                            "interface",
                            ("globals", "imports",),
                            self.interface_names_from_elem)

    # c.f. tree_python.py::PythonTreeEvaluator

    def _calltips_from_hit(self, hit):
        # TODO: compare with CitadelEvaluator._getSymbolCallTips()
        elem, scoperef = hit
        calltips = []
        if elem.tag == "variable":
            XXX
        elif elem.tag == "scope":
            ilk = elem.get("ilk")
            if ilk == "function":
                calltips.append(self._calltip_from_func(elem))
            elif ilk == "class":
                calltips.append(self._calltip_from_class(elem))
            else:
                raise NotImplementedError("unexpected scope ilk for "
                                          "calltip hit: %r" % elem)
        else:
            raise NotImplementedError("unexpected elem for calltip "
                                      "hit: %r" % elem)
        return calltips

    def _calltip_from_class(self, node):
        # If the class has a defined signature then use that.
        signature = node.get("signature")
        doc = node.get("doc")
        if signature:
            ctlines = signature.splitlines(0)
            if doc:
                ctlines += doc.splitlines(0)[:LINE_LIMIT-len(ctlines)]
            return '\n'.join(ctlines)

        # Alternatively we use calltip information on the class'
        # constructor. PHP does not automatically inherit class contructors,
        # so we just return the one on the current class.
        else:
            # In PHP our CIX classes may have a special constructor function
            # with the name "__construct".
            ctor = node.names.get("__construct")
            if ctor is not None:
                self.log("_calltip_from_class:: ctor is %r", ctor)
                return self._calltip_from_func(ctor)
            else:
                name = node.get("name")
                self.log("_calltip_from_class:: no ctor in class %r", name)
                return "%s()" % (name)

    def _members_from_elem(self, elem, name_prefix=''):
        """Return the appropriate set of autocomplete completions for
        the given element. Typically this is just one, but can be more for
        '*'-imports
        """
        members = set()
        if elem.tag == "import":
            alias = elem.get("alias")
            symbol_name = elem.get("symbol")
            module_name = elem.get("module")
            if symbol_name:
                #XXX Ignore failure to import.
                blob = import_handler.import_blob_name(
                            module_name, self.buf.libs, self.ctlr)
                if symbol_name == "*":
                    XXX
                else:
                    symbol = blob.names[symbol_name]
                    member_type = (symbol.get("ilk") or symbol.tag)
                    members.add( (member_type, alias or symbol_name) )
            else:
                cpln_name = alias or module_name.split('.', 1)[0]
                members.add( ("module", cpln_name) )
        else:
            members.add( (elem.get("ilk") or elem.tag,
                          name_prefix + elem.get("name")) )
        return members

    def _isElemInsideScoperef(self, elem, scoperef):
        blob, lpath = scoperef
        i = 0
        for i in range(len(lpath)):
            name = lpath[i]
            if name == elem.get("name"):
                check_elem = self._elem_from_scoperef((blob, lpath[:i+1]))
                if check_elem == elem:
                    # It's in the scope
                    return True
        return False

    def _members_from_hit(self, hit, allowProtected=None, allowPrivate=None):
        """Retrieve members from the given hit.

        @param hit {tuple} (elem, scoperef)
        """
        elem, scoperef = hit
        members = set()
        elem_name = elem.get("name")
        static_cplns = (self.trg.type == "static-members")
        for child in elem:
            name_prefix = ''   # Used to add "$" for static variable names.
            attributes = None
            if not allowProtected:
                attributes = child.get("attributes", "").split()
                # Protected and private vars can only be shown from inside
                # the class scope
                if "protected" in attributes:
                    if allowProtected is None:
                        # Need to check if it's allowed
                        allowProtected = self._isElemInsideScoperef(elem, self.get_start_scoperef())
                    if not allowProtected:
                        # Checked scope already and it does not allow protected
                        # Thats means it also does not allow private
                        allowPrivate = False
                        self.log("hit '%s.%s' is protected, not including",
                                 elem_name, child.get("name"))
                        continue
            if not allowPrivate:
                if attributes is None:
                    attributes = child.get("attributes", "").split()
                # we now know protected is allowed, now check private
                if "private" in attributes:
                    if allowPrivate is None:
                        # Need to check if it's allowed
                        allowPrivate = self._isElemInsideScoperef(elem, self.get_start_scoperef())
                    if not allowPrivate:
                        # Checked scope already and it does not allow private
                        self.log("hit '%s.%s' is private, not including",
                                 elem_name, child.get("name"))
                        continue
            if child.tag == "variable":
                if attributes is None:
                    attributes = child.get("attributes", "").split()
                if static_cplns:
                    if "static" not in attributes:
                        continue
                    name_prefix = '$'
                elif "static" in attributes:
                    continue
            # add the element, we've already checked private|protected scopes
            members.update(self._members_from_elem(child, name_prefix))
        if elem.get("ilk") == "class":
            for classref in elem.get("classrefs", "").split():
                self.debug("_members_from_hit: Getting members for inherited class: %r", classref)
                try:
                    subhit = self._hit_from_citdl(classref, scoperef)
                except CodeIntelError, ex:
                    # Continue with what we *can* resolve.
                    self.warn(str(ex))
                else:
                    if allowProtected is None:
                        # Need to check if it's allowed
                        allowProtected = self._isElemInsideScoperef(elem, self.get_start_scoperef())
                    # Checking the parent class, private is not allowed for sure
                    members.update(self._members_from_hit(subhit, allowProtected, allowPrivate=False))
        return members

    def _hit_from_citdl(self, expr, scoperef, defn_only=False):
        """Resolve the given CITDL expression (starting at the given
        scope) down to a non-import/non-variable hit.
        """
        self.log("_hit_from_citdl:: expr: %r, scoperef: %r", expr, scoperef)
        try:
            self._check_infinite_recursion(expr)
        except EvalError:
            # In the case of a recursion error, it is likely due to a class
            # variable having the same name as the class itself, so to try
            # to get better completions for this case we do not abort here,
            # but rather try from the parent scope instead. See bug:
            # http://bugs.activestate.com/show_bug.cgi?id=67774
            scoperef = self.parent_scoperef_from_scoperef(scoperef)
            if scoperef is None:
                # When we run out of scope, raise an error
                raise
            self.debug("_hit_from_citdl: recursion found for '%s', "
                       "moving to parent scope %r",
                       expr, scoperef)

        tokens = list(self._tokenize_citdl_expr(expr))
        self.log("_hit_from_citdl:: expr tokens: %r", tokens)

        # First part...
        hit, nconsumed = self._hit_from_first_part(tokens, scoperef)
        if not hit:
            #TODO: Add the fallback Buffer-specific near-by hunt
            #      for a symbol for the first token. See my spiral-bound
            #      book for some notes.
            raise CodeIntelError("could not resolve first part of '%s'" % expr)

        self.debug("_hit_from_citdl:: first part: %r -> %r",
                   tokens[:nconsumed], hit)

        # ...the remainder.
        remaining_tokens = tokens[nconsumed:]
        while remaining_tokens:
            self.debug("_hit_from_citdl:: resolve %r on %r in %r",
                       remaining_tokens, *hit)
            if remaining_tokens[0] == "()":
                #TODO: impl this function
                # _hit_from_call(elem, scoperef) -> hit or raise
                #   CodeIntelError("could resolve call on %r: %s", hit[0], ex)
                new_hit = self._hit_from_call(*hit)
                nconsumed = 1
            else:
                new_hit, nconsumed \
                    = self._hit_from_getattr(remaining_tokens, *hit)
            remaining_tokens = remaining_tokens[nconsumed:]
            hit = new_hit

        # Resolve any variable type inferences.
        #TODO: Need to *recursively* resolve hits.
        elem, scoperef = hit
        if elem.tag == "variable" and not defn_only:
            elem, scoperef = self._hit_from_variable_type_inference(elem, scoperef)

        self.info("_hit_from_citdl:: found '%s' => %s on %s", expr, elem, scoperef)
        return (elem, scoperef)

    def _elem_from_scoperef(self, scoperef):
        """A scoperef is (<blob>, <lpath>). Return the actual elem in
        the <blob> ciElementTree being referred to.
        """
        elem = scoperef[0]
        for lname in scoperef[1]:
            elem = elem.names[lname]
        return elem

    def _hit_from_first_part(self, tokens, scoperef):
        """Find a hit for the first part of the tokens.

        Returns (<hit>, <num-tokens-consumed>) or (None, None) if could
        not resolve.

        Example for 'os.sep':
            tokens: ('os', 'sep')
            retval: ((<variable 'sep'>,  (<blob 'os', [])),   1)
        Example for 'os.path':
            tokens: ('os', 'path')
            retval: ((<import os.path>,  (<blob 'os', [])),   2)
        """
        first_token = tokens[0]
        self.log("_hit_from_first_part:: find '%s ...' starting at %s:",
                 first_token, scoperef)

        if first_token in ("this", "self", "parent"):
            # Special handling for class accessors
            self.log("_hit_from_first_part:: Special handling for %r",
                     first_token)
            elem = self._elem_from_scoperef(scoperef)
            while elem is not None and elem.get("ilk") != "class":
                # Return the class element
                blob, lpath = scoperef
                if not lpath:
                    return (None, None)
                scoperef = blob, lpath[:-1]
                elem = self._elem_from_scoperef(scoperef)
            if not elem:
                return (None, None)
            self.log("_hit_from_first_part:: need %s for %r", first_token, elem)
            if first_token == "parent":
                first_token = elem.get("classrefs")
                self.log("_hit_from_first_part:: Special handling for parent, "
                         "classref %r", first_token)
                if not first_token:
                    return (None, None)
                # Change scope to global scope
                tokens = [first_token] + tokens[1:]
                scoperef = self._get_global_scoperef(scoperef)
                # Now go below and find the parent class members
            elif self._return_with_hit((elem, scoperef), 1):
                self.log("_hit_from_first_part:: %s returning scoperef: %r",
                         first_token, scoperef)
                return (elem, scoperef), 1

        while 1:
            self.log("_hit_from_first_part:: scoperef now %s:", scoperef)
            elem = self._elem_from_scoperef(scoperef)
            if first_token in elem.names:
                first_token_elem = elem.names[first_token]
                if self._return_with_hit((first_token_elem, scoperef), 1):
                    #TODO: skip __hidden__ names
                    self.log("_hit_from_first_part:: is '%s' accessible on %s? "
                             "yes: %s", first_token, scoperef, first_token_elem)
                    return (first_token_elem, scoperef), 1

            self.log("_hit_from_first_part:: is '%s' accessible on %s? no", first_token, scoperef)
            # Do not go past the global scope reference
            if len(scoperef[1]) >= 1:
                scoperef = self.parent_scoperef_from_scoperef(scoperef)
                assert scoperef and scoperef[0] is not None, "Something is " \
                        "seriously wrong with our php logic."
            else:
                # We shall fallback to imports then
                break

        # elem and scoperef *are* for the global level
        hit, nconsumed = self._hit_from_elem_imports(tokens, elem)
        if hit is not None and self._return_with_hit(hit, nconsumed):
            self.log("_hit_from_first_part:: is '%s' accessible on %s? yes, "
                     "imported: %s",
                     '.'.join(tokens[:nconsumed]), scoperef, hit[0])
            return hit, nconsumed
        return None, None


    def _hit_from_elem_imports(self, tokens, elem):
        """See if token is from one of the imports on this <scope> elem.

        Returns (<hit>, <num-tokens-consumed>) or (None, None) if not found.
        """
        #PERF: just have a .import_handler property on the evalr?
        self.debug("_hit_from_elem_imports:: Checking imports, tokens[0]: %r "
                   "... imp_elem: %r", tokens[0], elem)
        import_handler = self.citadel.import_handler_from_lang(self.trg.lang)
        libs = self.buf.libs

        #PERF: Add .imports method to ciElementTree for quick iteration
        #      over them. Or perhaps some cache to speed this method.
        #TODO: The right answer here is to not resolve the <import>,
        #      just return it. It is complicated enough that the
        #      construction of members has to know the original context.
        #      See the "Foo.mypackage.<|>mymodule.yo" part of test
        #      python/cpln/wacky_imports.
        #      XXX Not totally confident that this is the right answer.
        first_token = tokens[0]
        for imp_elem in (i for i in elem if i.tag == "import"):
            self.debug("_hit_from_elem_imports:: import '%s ...' from %r?",
                       tokens[0], imp_elem)
            module_name = imp_elem.get("module")
            try_module_names = [module_name]
            # If a module import is absolute and it fails, try a relative one
            # as well. Example:
            #   include (MYDIR + "/file.php");
            if module_name[0] == "/":
                try_module_names.append(module_name[1:])
            for module_name in try_module_names:
                if module_name not in self._imported_blobs:
                    try:
                        blob = import_handler.import_blob_name(
                                    module_name, libs, self.ctlr)
                    except CodeIntelError:
                        self.debug("_hit_from_elem_imports:: Failed import: %s",
                                   module_name)
                        pass # don't freak out: might not be our import anyway
                    else:
                        self._imported_blobs[module_name] = 1
                        try:
                            hit, nconsumed = self._hit_from_getattr(
                                                tokens, blob, (blob, []))
                            if hit:
                                return hit, nconsumed
                        except CodeIntelError, e:
                            self.debug("_hit_from_elem_imports:: "
                                       "_hit_from_getattr could not resolve: "
                                       "%r on %r", tokens, blob)
                            pass # don't freak out: we'll try the next import
                else:
                    self.debug("_hit_from_elem_imports:: Recursive import: "
                               "Already imported module: %r", module_name)

        # include-everything stuff
        self.log("_hit_from_elem_imports:: trying import everything: tokens: "
                 "%r", tokens)
        #self.log(banner("include-everything stuff", length=50))

        # First check the full lpath, then try for smaller and smaller lengths
        for nconsumed in range(len(tokens), 0, -1):
            lpath = tuple(tokens[:nconsumed])
            self.log("_hit_from_elem_imports:: trying with lpath: %r", lpath)
            # for each directory in all known php file directories
            for lib in self.libs:
                # see if there is a match (or partial match) in this directory
                hits = lib.hits_from_lpath(lpath, self.ctlr,
                                              curr_buf=self.buf)
                self.log("_hit_from_elem_imports:: ie: lookup %r in %s => %r",
                         lpath, lib, hits)
                for hit in hits:
                    (hit_elem, import_scoperef) = hit
                    (hit_blob, hit_lpath) = import_scoperef
                    self.log("_hit_from_elem_imports:: ie: matched %r to %r "
                             "in blob %r", lpath, hit_elem, hit_blob, )
                    unique_import_name = hit_blob.get("name") + "#" + str(lpath)
                    #print unique_import_name
                    if unique_import_name not in self._imported_blobs:
                        self._imported_blobs[unique_import_name] = 1
                        try:
                            if hit and self._return_with_hit(hit, 1):
                                return hit, nconsumed
                        except CodeIntelError, e:
                            self.debug("_hit_from_elem_imports:: ie: "
                                       "_hit_from_getattr could not resolve: "
                                       "%r on %r", tokens, blob)
                            pass # don't freak out: we'll try the next import
                    else:
                        self.debug("_hit_from_elem_imports:: ie: Recursive "
                                   "import: Already imported module: %r",
                                   unique_import_name)
            self.log("_hit_from_elem_imports:: ie: no matches found")
            #self.log(banner(None, length=50))

        return None, None

    def _hit_from_getattr(self, tokens, elem, scoperef):
        """Return a hit for a getattr on the given element.

        Returns (<hit>, <num-tokens-consumed>) or raises an EvalError.

        Typically this just does a getattr of tokens[0], but handling
        some multi-level imports can result in multiple tokens being
        consumed.
        """
        #TODO: On failure, call a hook to make an educated guess. Some
        #      attribute names are strong signals as to the object type
        #      -- typically those for common built-in classes.
        first_token = tokens[0]
        self.log("_hit_from_getattr:: resolve '%s' on %r in %r:", first_token,
                 elem, scoperef)
        if elem.tag == "variable":
            elem, scoperef = self._hit_from_variable_type_inference(elem, scoperef)

        assert elem.tag == "scope"
        ilk = elem.get("ilk")
        if ilk == "function":
            # Internal function arguments and variable should
            # *not* resolve. And we don't support function
            # attributes.
            pass
        elif ilk == "class":
            attr = elem.names.get(first_token)
            if attr is not None:
                self.log("_hit_from_getattr:: attr is %r in %r", attr, elem)
                classname = elem.get("name")
                # XXX - This works, but does not feel right.
                # Add the class name if it's not already there
                if len(scoperef[1]) == 0 or scoperef[1][-1] != classname:
                    class_scoperef = (scoperef[0], scoperef[1]+[classname])
                else:
                    class_scoperef = scoperef
                return (attr, class_scoperef), 1
            for classref in elem.get("classrefs", "").split():
                #TODO: update _hit_from_citdl to accept optional node type,
                #      i.e. to only return classes in this case.
                self.log("_hit_from_getattr:: is '%s' available on parent "
                         "class: %r?", first_token, classref)
                base_elem, base_scoperef \
                    = self._hit_from_citdl(classref, scoperef)
                if base_elem is not None and base_elem.get("ilk") == "class":
                    self.log("_hit_from_getattr:: is '%s' from %s base class?",
                             first_token, base_elem)
                    try:
                        hit, nconsumed = self._hit_from_getattr(tokens,
                                                                base_elem,
                                                                base_scoperef)
                        if hit is not None and self._return_with_hit(hit,
                                                                     nconsumed):
                            self.log("_hit_from_getattr:: is '%s' accessible "
                                     "on %s? yes: %s",
                                     '.'.join(tokens[:nconsumed]), scoperef,
                                     hit[0])
                            return hit, nconsumed
                    except CodeIntelError, e:
                        pass # don't freak out: we'll try the next classref
        elif ilk == "blob":
            attr = elem.names.get(first_token)
            if attr is not None:
                self.log("_hit_from_getattr:: attr is %r in %r", attr, elem)
                return (attr, scoperef), 1

            hit, nconsumed = self._hit_from_elem_imports(tokens, elem)
            if hit is not None:
                return hit, nconsumed
        else:
            raise NotImplementedError("unexpected scope ilk: %r" % ilk)
        raise CodeIntelError("could not resolve '%s' getattr on %r in %r"
                             % (first_token, elem, scoperef))

    def _hit_from_call(self, elem, scoperef):
        """Resolve the function call inference for 'elem' at 'scoperef'."""
        citdl = elem.get("returns")
        if not citdl:
            raise CodeIntelError("no _hit_from_call info for %r" % elem)
        self.log("_hit_from_call: resolve '%s' for %r, lpath: %r", citdl, elem, scoperef[1])
        # scoperef has to be on the function called
        func_scoperef = (scoperef[0], scoperef[1]+[elem.get("name")])
        return self._hit_from_citdl(citdl, func_scoperef)

    def _hit_from_variable_type_inference(self, elem, scoperef):
        """Resolve the type inference for 'elem' at 'scoperef'."""
        citdl = elem.get("citdl")
        if not citdl:
            raise CodeIntelError("no type-inference info for %r" % elem)
        self.log("_hit_from_variable_type_inference:: resolve '%s' type inference for %r:", citdl, elem)
        return self._hit_from_citdl(citdl, scoperef)

    def parent_scoperef_from_scoperef(self, scoperef):
        # For PHP, either it's in the current scope or it's in the global scope
        # or last of all, it's in the builtins
        blob, lpath = scoperef
        if blob is self._built_in_blob:
            # Nothin past the builtins
            return None
        elif len(lpath) >= 1:
            # Return the global scope
            return self._get_global_scoperef(scoperef)
        else:
            return (self.built_in_blob, [])


    #--- These method were inherited from JavaScriptTreeEvaluator.
    # If they are generic enough they should be moved to base
    # TreeEvaluator.

    _built_in_blob = None
    @property
    def built_in_blob(self):
        if self._built_in_blob is None:
            self._built_in_blob = self.buf.stdlib.get_blob("*")
        return self._built_in_blob

    _built_in_cache = None
    @property
    def built_in_cache(self):
        if self._built_in_cache is None:
            phpcache = self.built_in_blob.cache.get('php')
            if phpcache is None:
                phpcache = {}
                self.built_in_blob.cache['php'] = phpcache
            self._built_in_cache = phpcache
        return self._built_in_cache

    def _tokenize_citdl_expr(self, expr):
        for tok in expr.split('.'):
            if tok.endswith('()'):
                yield tok[:-2]
                yield '()'
            else:
                yield tok
    def _join_citdl_expr(self, tokens):
        return '.'.join(tokens).replace('.()', '()')

    def _calltip_from_func(self, node):
        # See "Determining a Function CallTip" in the spec for a
        # discussion of this algorithm.
        from codeintel2.util import LINE_LIMIT
        signature = node.get("signature")
        doc = node.get("doc")
        ctlines = []
        if not signature:
            name = node.get("name")
            #XXX Note difference for Tcl in _getSymbolCallTips.
            ctlines = [name + "(...)"]
        else:
            ctlines = signature.splitlines(0)
        if doc:
            ctlines += doc.splitlines(0)[:LINE_LIMIT-len(ctlines)]
        return '\n'.join(ctlines)


    #---- Internal Utility functions for PHP

    def _get_global_scoperef(self, scoperef):
        return (scoperef[0], [])

    def _convertListToCitdl(self, citdl_type, lst):
        return sorted([ (citdl_type, v) for v in lst ])

    def _make_shortname_lookup_citdl_dict(self, citdl_type, namelist, length=1):
        d = make_short_name_dict(namelist, length=length)
        for key, values in d.items():
            d[key] = self._convertListToCitdl(citdl_type, values)
        return d

    # XXX PERF : Anything below here is in need of performance tweaking

    def _get_all_children_with_details(self, node, tagname, attributes=None, startswith=None):
        """Returns a list of child nodes that have the tag name and attributes.
        
        @param node {Element} the base node to search from
        @param tagname {str} the child tag name to find
        @param attributes {dict} the child node must have these attributes
        @param startswith {str} the child node name must start with this string
        @returns list of matched Element nodes
        """
        result = []
        for childnode in node.getchildren():
            if childnode.tag == tagname:
                doesMatch = True
                if attributes:
                    for attrname, attrvalue in attributes.items():
                        if childnode.get(attrname) != attrvalue:
                            doesMatch = False
                            break
                if doesMatch and startswith:
                    name = childnode.get("name")
                    if not name or not name.startswith(startswith):
                        doesMatch = False
                if doesMatch:
                    result.append(childnode)
        return result

    def _get_import_blob_with_module_name(self, module_name):
        import_handler = self.citadel.import_handler_from_lang(self.trg.lang)
        libs = self.buf.libs
        try:
            return import_handler.import_blob_name(module_name, libs,
                                                   self.ctlr)
        except CodeIntelError:
            pass # don't freak out: might not be our import anyway

    # Only used by _get_all_import_blobs_for_elem
    def _get_all_import_blobs_dict_for_elem(self, elem, imported_blobs):
        """Return all imported php blobs for the given element
        @param elem {Element} The element to find imports from.
        @param imported_blobs {dict} key: import name, value: imported blob
        """
        for imp_elem in (i for i in elem if i.tag == "import"):
            module_name = imp_elem.get("module")
            self.debug("_get_all_import_blobs_dict_for_elem:: Getting imports from %r", module_name)
            if module_name and module_name not in imported_blobs:
                import_blob = self._get_import_blob_with_module_name(module_name)
                if import_blob is not None:
                    imported_blobs[module_name] = import_blob
                    # Get imports from imports
                    # Example, foo imports bar, bar imports baz
                    self._get_all_import_blobs_dict_for_elem(import_blob, imported_blobs)
            else:
                self.debug("_get_all_import_blobs_dict_for_elem:: Recursive import: Already imported module: %r",
                           module_name)

    def _get_all_import_blobs_for_elem(self, elem):
        """Return all imported php blobs for the given element
        @param elem {Element} The element to find imports from.
        """
        # imported_blobs is used to keep track of what we import and to ensure
        # we don't get a recursive import situation
        imported_blobs = {}
        self._get_all_import_blobs_dict_for_elem(elem, imported_blobs)
        blobs = imported_blobs.values()
        self.debug("_get_all_import_blobs_for_elem:: Imported blobs: %r", blobs)
        return blobs

    #_built_in_keyword_names = None
    #@property
    #def built_in_keyword_names(self):
    #    if self._built_in_keyword_names is None:
    #        # Get all class names from the nodes
    #        # XXX - Fix keywords
    #        self._built_in_keyword_names = ["print", "echo", "class", "function"]
    #    return self._built_in_keyword_names

    def _php_cache_from_elem(self, elem):
        cache = elem.cache.get('php')
        if cache is None:
            # Add one in then
            cache = {}
            elem.cache['php'] = cache
        return cache

    def variable_names_from_elem(self, elem, cache_item_name='variable_names'):
        cache = self._php_cache_from_elem(elem)
        variable_names = cache.get(cache_item_name)
        if variable_names is None:
            variables = self._get_all_children_with_details(elem, "variable")
            variable_names = [ x.get("name") for x in variables ]
            cache[cache_item_name] = variable_names
        return variable_names

    def function_names_from_elem(self, elem, cache_item_name='function_names'):
        cache = self._php_cache_from_elem(elem)
        function_names = cache.get(cache_item_name)
        if function_names is None:
            functions = self._get_all_children_with_details(elem, "scope",
                                                            {"ilk": "function"})
            function_names = [ x.get("name") for x in functions ]
            cache[cache_item_name] = function_names
        return function_names

    def function_shortnames_from_elem(self, elem, cache_item_name='function_shortnames'):
        cache = self._php_cache_from_elem(elem)
        function_short_names = cache.get(cache_item_name)
        if function_short_names is None:
            function_short_names = make_short_name_dict(
                                    self.function_names_from_elem(elem),
                                    # XXX - TODO: Use FUNCTION_TRIGGER_LEN instead of hard coding 3
                                    length=3)
            cache[cache_item_name] = function_short_names
        return function_short_names

    def class_names_from_elem(self, elem, cache_item_name='class_names'):
        cache = self._php_cache_from_elem(elem)
        class_names = cache.get(cache_item_name)
        if class_names is None:
            classes = self._get_all_children_with_details(elem, "scope",
                                                            {"ilk": "class"})
            class_names = [ x.get("name") for x in classes ]
            cache[cache_item_name] = class_names
        return class_names

    def interface_names_from_elem(self, elem, cache_item_name='interface_names'):
        cache = self._php_cache_from_elem(elem)
        interface_names = cache.get(cache_item_name)
        if interface_names is None:
            interfaces = self._get_all_children_with_details(elem, "scope",
                                                            {"ilk": "interface"})
            interface_names = [ x.get("name") for x in interfaces ]
            cache[cache_item_name] = interface_names
        return interface_names
