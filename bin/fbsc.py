#!/usr/bin/env python
# Copyleft BogDan Vatra

import argparse
import os
import sys
import importlib
import pprint
import types

from pyparsing import *

fbs_files = {}
parsed_files = {}

fbs_types = {'bool', 'byte', 'ubyte', 'short', 'ushort', 'int', 'uint', 'float', 'long', 'ulong', 'double', 'string'}

def fbs_schema():
    """
    Create FBS IDL BNF
    """

    # include_decl = include string_constant ;
    include_decl = Group(Keyword('include') + QuotedString('"') + Suppress(';'))

    # ident_decl = some_ident
    ident_decl = Word(alphanums + "_.")
    ident_or_quoted_string = Or([ident_decl, QuotedString('"')])

    # namespace_decl = namespace ident ( . ident )* ;
    namespace_decl = Group(Keyword("namespace") + ident_decl + Suppress(';'))

    # option_decl = option ident = string_constant ;
    option_decl = Group(Keyword("option") + ident_decl + Suppress('=') +
                  ident_or_quoted_string + Suppress(';'))

    # attribute_decl = attribute string_constant ;
    attribute_decl = Group(Keyword('attribute') + QuotedString('"') + Suppress(';'))



    # metadata = [ ( commasep( ident [ : single_value ] ) ) ]
    metadata_value_decl = Group(ident_decl + Optional(Suppress(':') +
                                ident_or_quoted_string))
    metadata_decl = Optional(Group(Suppress('(') + metadata_value_decl +
                          ZeroOrMore(Suppress(',') + metadata_value_decl) +
                          Suppress(')')))

    # field_decl = ident : type [ = scalar ] metadata ;
    field_decl = Group(ident_decl + Suppress(':') +
                       Group(Optional("[") + Word(alphanums) + Optional("]")) +
                       Optional(Suppress('=') + ident_or_quoted_string) +
                       metadata_decl +
                       Suppress(';'))

    # type_decl = ( table | struct ) ident metadata { field_decl+ }
    type_decl = Group(Or([Keyword('table'), Keyword('struct')]) + Group(ident_decl + metadata_decl) +
                      Suppress('{') +
                        Group(ZeroOrMore(field_decl)) +
                      Suppress('}'))

    # enumval_decl = ident [ = integer_constant ]
    enumval_decl = Group(ident_decl + Optional(Suppress("=") + Word(alphanums + "_.<< |")))

    # enum_decl = ( enum | union ) ident [ : type ] metadata { commasep( enumval_decl ) }
    enum_decl = Group(Or([Keyword('enum'), Keyword('union')]) +
                    Group(ident_decl + Optional(Suppress(":") + ident_decl) + metadata_decl) +
                      Suppress('{') +
                        Group(ZeroOrMore(enumval_decl + Suppress(",")) +
                        Optional(enumval_decl)) +
                      Suppress('}'))

    # root_decl = root_type ident ;
    root_decl = Group(Keyword('root_type') + ident_decl + Suppress(';'))

    # file_extension_decl = file_extension string_constant ;
    file_extension_decl = Group(Keyword('file_extension') + QuotedString('"') + Suppress(';'))

    # file_identifier_decl = file_identifier string_constant ;
    file_identifier_decl = Group(Keyword('file_identifier') + QuotedString('"') + Suppress(';'))

    items_decl = (namespace_decl | attribute_decl | option_decl | type_decl | enum_decl)
    final_decl = (root_decl | file_extension_decl | file_identifier_decl)

    # schema = include* ( namespace_decl | type_decl | enum_decl | root_decl |
    #                     file_extension_decl | file_identifier_decl | attribute_decl |
    #                     object )*
    schema = (ZeroOrMore(include_decl) + ZeroOrMore(items_decl) + ZeroOrMore(final_decl))
    schema.ignore(cppStyleComment)

    return schema

class FbsEnum:
    """ """
    def __init__(self, fbs_file, enum_token):
        self.name = enum_token[1][0]
        self.fully_qualified_name = fbs_file.fully_qualified_type_name(self.name, False)
        self.type = ''
        self.bit_flags = False
        self.values = []
        fbs_file.types[self.fully_qualified_name] = {'type':'enum'}

        if len(enum_token[1]) > 1:
            token = enum_token[1][1]
            if isinstance(token, types.StringTypes):
                self.parse_enum_type(token)
            else:
                self.parse_enum_options(token)

            if len(enum_token[1]) == 3:
                self.parse_enum_options(enum_token[1][2])

        for key_val in enum_token[2]:
            kv = {}
            if len(key_val) == 2:
                kv = {'key':key_val[0], 'value':key_val[1]}
            else:
                kv = {'key':key_val[0], 'value':''}
            self.values.append(kv)
            fbs_file.types[self.fully_qualified_name + '.' + kv['key']] = {'type':'enum_key', 'value':kv['value']}

    def parse_enum_type(self, type):
        non_enum_types = ['bool', 'float', 'double', 'string']
        if type not in fbs_types or type in non_enum_types:
            raise Exception('enum type must be integral')
        self.type = type;

    def parse_enum_options(self, options):
        if len(options) != 1 or len(options[0]) != 1 or options[0][0] != 'bit_flags':
            raise Exception('Unknow enum option')
        self.bit_flags = True

    def debug(self):
        print 'Enum self.name=', self.name
        print '     self.fully_qualified_name=', self.fully_qualified_name
        print '     self.type=', self.type
        print '     self.bit_flags=', self.bit_flags
        print '     self.values=', self.values

class FbsUnion:
    """ """
    def __init__(self, fbs_file, union_token):
        self.name = union_token[1][0]
        self.fully_qualified_name = fbs_file.fully_qualified_type_name(self.name, False)
        self.values = []
        fbs_file.types[self.fully_qualified_name] = {'type':'union'}

        for key_val in union_token[2]:
            self.values.append(key_val[0])

    def debug(self):
        print 'Union self.name=', self.name
        print '     self.fully_qualified_name=', self.fully_qualified_name
        print '     self.values=', self.values

class FbsBaseStructTable:
    def __init__(self, fbs_file, tokens):
        # print  fbs_file, tokens[2]
        self.name = tokens[1][0]
        self.fully_qualified_name = fbs_file.fully_qualified_type_name(self.name, False)
        self.metadata = tokens[1][1] if len(tokens[1]) == 2 else []
        self.fields = []
        for field in tokens[2]:
            self.fields.append({
                  'name' : field[0],
                  'type' : field[1][0] if len(field[1]) == 1 else field[1][1],
                  'is_array' : False if len(field[1]) == 1 else True,
                  'value' : field[2] if len(field) >= 3 and isinstance(field[2], types.StringTypes) else '',
                  'metadata' : '' if len(field) == 2 or (len(field) == 3 and isinstance(field[2], types.StringTypes)) else field[2] if len(field) == 3 else field[3]
                  })

    def debug(self):
        print '       self.fully_qualified_name=', self.fully_qualified_name
        print '       self.metadata=', self.metadata
        print '       self.fields=', self.fields

class FbsTable(FbsBaseStructTable):
    def __init__(self, fbs_file, tokens):
        FbsBaseStructTable.__init__(self, fbs_file, tokens)
        fbs_file.types[self.fully_qualified_name] = {'type':'table'}

    def set_medatada(self):
        if len(self.metadata) == 0:
            raise Exception('Buggy metadata')

    def debug(self):
        print 'Table  self.name=', self.name
        FbsBaseStructTable.debug(self)

class FbsStruct(FbsBaseStructTable):
    def __init__(self, fbs_file, tokens):
        FbsBaseStructTable.__init__(self, fbs_file, tokens)
        fbs_file.types[self.fully_qualified_name] = {'type':'struct'}

    def set_medatada(self):
        if len(self.metadata) == 0:
            raise Exception('Buggy metadata')

    def debug(self):
        print 'Struct self.name=', self.name
        FbsBaseStructTable.debug(self)

class FbsFile:
    """ """
    def __init__(self, file_path):
        self.file_path = file_path
        self.current_namespace = ""
        self.options = {}
        self.attributes = set()
        self.enums = []
        self.unions = []
        self.tables = []
        self.structs = []
        self.types = {}
        self.root_type = ''
        self.file_identifier = ''
        self.file_extension = ''
        self.fully_parsed = False
        parsed_files[file_path] = self
        schema = fbs_schema()
        tokens = schema.parseFile(file_path)

        parsers = {
                    'include': self.parse_include,
                    'namespace': self.parse_namespace,
                    'attribute': self.parse_attribute,
                    'option': self.parse_option,
                    'enum': self.parse_enum,
                    'union': self.parse_union,
                    'table': self.parse_table,
                    'struct': self.parse_struct,
                    'root_type': self.parse_root_type,
                    'file_extension': self.parse_file_extension,
                    'file_identifier': self.parse_file_identifier,
                  }

        for token in tokens:
            if token[0] in parsers.keys():
                parsers[token[0]](token)
            else:
                raise Exception('Unhandled token: ' + token[0])

        self.fully_parsed = True
        self.debug()

    def fully_qualified_type_name(self, type, ScalasTypes=True):
        if ScalasTypes and type in fbs_types:
            return type
        if len(self.current_namespace) > 0 and type.find('.') == -1:
            return self.current_namespace + type
        return type

    def checked_type(self, type, ScalasTypes=True):
        type_name = self.fully_qualified_type_name(type, ScalasTypes)
        if not type_name in self.types.keys():
            raise Exception('Undefined type "'+ type_name +'"')
        return type

    def parse_include(self, include_tokens):
        if self.file_path == include_tokens[1]:
            return
        if include_tokens[1] in parsed_files.keys():
            fbsObject = parsed_files[include_tokens[1]]
            if not fbsObject.fully_parsed:
                raise Exception('Circular includes detected: "' + self.file_path + '" includes "' + include_tokens[1] + '"')
            else:
                self.types |= fbsObject.types
        self.types |= FbsFile(include_tokens[1]).types

    def parse_namespace(self, namespace_tokens):
        self.current_namespace = namespace_tokens[1] + '.'

    def parse_attribute(self, tokens):
        self.attributes.add(tokens[1])

    def parse_option(self, tokens):
        if not tokens[1] in self.options.keys():
            self.options[tokens[1]] = set()
        self.options[tokens[1]].add(tokens[2])

    def parse_enum(self, tokens):
        self.enums.append(FbsEnum(self, tokens))

    def parse_union(self, tokens):
        self.unions.append(FbsUnion(self, tokens))

    def parse_table(self, tokens):
        self.tables.append(FbsTable(self, tokens))

    def parse_struct(self, tokens):
        self.structs.append(FbsStruct(self, tokens))

    def parse_root_type(self, tokens):
        if self.root_type:
            raise Exception('root_type already set as "' + self.root_type + '"')
        self.root_type = self.checked_type(tokens[1], False)

    def parse_file_extension(self,tokens):
        if self.file_extension:
            raise Exception('file_extensione already set as "' + self.file_extension + '"')
        self.file_extension = tokens[1]

    def parse_file_identifier(self, tokens):
        if self.file_identifier:
            raise Exception('file_identifier already set as "' + self.file_identifier + '"')
        if len(tokens[1]) != 4:
            raise Exception('file_identifier must be exactly 4 characters')
        self.file_identifier = tokens[1]

    def debug(self):
        print 'self.file_path=', self.file_path
        print 'self.current_namespace=', self.current_namespace
        print 'self.options=', self.options
        print 'self.attributes=', self.attributes
        for lst in [self.enums, self.unions, self.tables, self.structs]:
            for obj in lst:
                obj.debug()
        print 'self.types=', self.types
        print 'self.root_type=', self.root_type
        print 'self.file_identifier=', self.file_identifier
        print 'self.file_extension=', self.file_extension
        return self

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=('flatbuffers schemas'))
    parser.add_argument( "files", nargs = "+" )
    parser.add_argument( '-o', '--outputdir', action='store', default = "",
                         help = "Prefix directory for all generated files.")
    parser.add_argument( '-g', '--generator', action='store', default = "c++",
                         help = "Which generator to use (e.g. c++, java, python, etc.)")
    args = parser.parse_args()

    sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/extensions/common')
    sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/extensions/generators')

    # try:
    for fbs in args.files:
         fbs_files[fbs] = FbsFile(fbs)
    # except Exception as e:
    #      print (e)
