#
# Copyright (c) 2016 Intel Corporation.
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""\
This module implements a simple expression language.

The grammar for this language is as follows:

    expression ::= expression "and" expression
                 | expression "or" expression
                 | "not" expression
                 | "(" expression ")"
                 | symbol "==" constant
                 | symbol "!=" constant
                 | symbol "<" number
                 | symbol ">" number
                 | symbol ">=" number
                 | symbol "<=" number
                 | symbol "in" list
                 | constant "in" symbol
                 | symbol

    list ::= "[" list_contents "]"

    list_contents ::= constant
                    | list_contents "," constant

    constant ::= number
               | boolean
               | string

When symbols are encountered, they are looked up in an environment
dictionary supplied to the parse() function.

For the case where

    expression ::= symbol

it evaluates to true if the symbol is defined to a non-empty
string. Note thus::

  SOMESYMBOL

Will evaluate as *False* if *SOMESYMBOL* is a *False* boolean; if you
want to test for a symbol being defined and being boolean *False*, use::

  SOMESYMBOL == False

For all comparison operators, if the config symbol is undefined, it will
be treated as a 0 (for > < >= <=) or an empty string "" (for == != in).
For numerical comparisons it doesn't matter if the environment stores
the value as an integer or string, it will be cast appropriately.

Operator precedence, starting from lowest to highest:

    or (left associative)
    and (left associative)
    not (right associative)
    all comparison operators (non-associative)

The ':' operator compiles the string argument as a regular expression,
and then returns a true value only if the symbol's value in the environment
matches. For example, if CONFIG_SOC="quark_se" then

    filter = CONFIG_SOC : "quark.*"

Would match it.

"""

import copy
import numbers
import re
import threading

import ply.lex as lex
import ply.yacc as yacc

import commonl

reserved = {
    'and' : 'AND',
    'or' : 'OR',
    'not' : 'NOT',
    'in' : 'IN',
}

tokens = [
    "BOOL",
    "HEX",
    "STR",
    "INTEGER",
    "EQUALS",
    "NOTEQUALS",
    "LT",
    "GT",
    "LTEQ",
    "GTEQ",
    "OPAREN",
    "CPAREN",
    "OBRACKET",
    "CBRACKET",
    "COMMA",
    "SYMBOL",
    "COLON",
] + list(reserved.values())

def t_BOOL(t):
    r"([Tt]rue|[Ff]alse)"
    # Any token that says true or false is a boolean
    #
    # note we have matched against a text regex, so t.value is str
    # already
    value = t.value.lower()
    if value == "true":
        t.value = True
    else:
        t.value = False
    return t

def t_HEX(t):
    r"0x[0-9a-fA-F]+"
    t.value = int(t.value, 16)
    return t

def t_INTEGER(t):
    r"\d+"
    t.value = int(t.value)
    return t

def t_STR(t):
    r'\"([^\\\n]|(\\.))*?\"|\'([^\\\n]|(\\.))*?\''
    # nip off the quotation marks
    t.value = t.value[1:-1]
    return t

t_EQUALS = r"=="

t_NOTEQUALS = r"!="

t_LT = r"<"

t_GT = r">"

t_LTEQ = r"<="

t_GTEQ = r">="

t_OPAREN = r"[(]"

t_CPAREN = r"[)]"

t_OBRACKET = r"\["

t_CBRACKET = r"\]"

t_COMMA = r","

t_COLON = ":"

class _t_symbol_c(str):
    def __init__(self, s):
        str.__init__(s)

def t_SYMBOL(t):
    r"[A-Za-z_][-/\.0-9A-Za-z_]*"
    t.type = reserved.get(t.value, "SYMBOL")
    t.value = _t_symbol_c(t.value)
    return t

t_ignore = " \t\n"

def t_error(t):
    raise SyntaxError("Unexpected token '%s'" % t.value)

lex.lex()

precedence = (
    ('left', 'OR'),
    ('left', 'AND'),
    ('right', 'NOT'),
    ('nonassoc' , 'EQUALS', 'NOTEQUALS', 'GT', 'LT', 'GTEQ', 'LTEQ', 'IN'),
)

def p_expr_or(p):
    'expr : expr OR expr'
    p[0] = ("or", p[1], p[3])

def p_expr_and(p):
    'expr : expr AND expr'
    p[0] = ("and", p[1], p[3])

def p_expr_not(p):
    'expr : NOT expr'
    p[0] = ("not", p[2])

def p_expr_parens(p):
    'expr : OPAREN expr CPAREN'
    p[0] = p[2]

def p_expr_eval(p):
    """expr : SYMBOL EQUALS const
            | SYMBOL NOTEQUALS const
            | SYMBOL GT number
            | SYMBOL LT number
            | SYMBOL GTEQ number
            | SYMBOL LTEQ number
            | SYMBOL IN list
            | SYMBOL IN SYMBOL
            | STR IN SYMBOL
            | HEX IN SYMBOL
            | INTEGER IN SYMBOL
            | SYMBOL COLON STR"""
    p[0] = (p[2], p[1], p[3])

def p_expr_single(p):
    """expr : SYMBOL"""
    p[0] = ("exists", p[1])

def p_list(p):
    """list : OBRACKET list_intr CBRACKET"""
    p[0] = p[2]

def p_list_intr_single(p):
    """list_intr : const"""
    p[0] = [p[1]]

def p_list_intr_mult(p):
    """list_intr : list_intr COMMA const"""
    p[0] = copy.copy(p[1])
    p[0].append(p[3])

def p_const(p):
    # note we try to evaluate BOOLs before STRs since they can be a
    # "True/true/False/flase" so we don't confuse them w strings
    """const : BOOL
             | number
             | STR"""
    p[0] = p[1]

def p_number(p):
    """number : INTEGER
              | HEX"""
    p[0] = p[1]

def p_error(p):
    if p:
        raise SyntaxError("Unexpected token '%s'" % p.value)
    else:
        raise SyntaxError("Unexpected end of expression")

parser = yacc.yacc(debug=False, write_tables=False)

def ast_sym(ast, env):
    if ast in env:
        e = env[ast]
        # Ugly, but I am not sure of what is a better way to do this.
        if isinstance(e, dict) or isinstance(e, set) or isinstance(e, list) :
            return env[ast]
        if isinstance(e, bool):
            return e
        if isinstance(e, numbers.Number):
            return e
        return str(e)

    return ""

def ast_sym_int(ast, env):
    if ast in env:
        return int(env[ast])
    return 0

def ast_expr(ast, env):
    if ast[0] == "not":
        return not ast_expr(ast[1], env)
    elif ast[0] == "or":
        return ast_expr(ast[1], env) or ast_expr(ast[2], env)
    elif ast[0] == "and":
        return ast_expr(ast[1], env) and ast_expr(ast[2], env)
    elif ast[0] == "==":
        return ast_sym(ast[1], env) == ast[2]
    elif ast[0] == "!=":
        return ast_sym(ast[1], env) != ast[2]
    elif ast[0] == ">":
        return ast_sym_int(ast[1], env) > int(ast[2])
    elif ast[0] == "<":
        return ast_sym_int(ast[1], env) < int(ast[2])
    elif ast[0] == ">=":
        return ast_sym_int(ast[1], env) >= int(ast[2])
    elif ast[0] == "<=":
        return ast_sym_int(ast[1], env) <= int(ast[2])
    elif ast[0] == "in":
        def _val_get(val):
            # FIXME: horrible hack
            #
            # because we have an import hell which mixes relative and
            # absolute imports, we end up w Python3 confused on the
            # type of the instance of this object we instantiated as
            # _t_symbol_c but it saying it is
            # tcfl.commonl.expr_parser._t_symbol_c.
            #
            # Thus the right code:
            #
            ## if repr(val.__class__)val.__class__.isinstance(val, _t_symbol_c):
            #
            # doesn't work.
            #
            # So until we have this fixed, this horrible hack does it.
            if "_t_symbol_c'" in repr(val.__class__):
                return ast_sym(val, env)
            else:
                return val
        symbol_left = ast[1]
        val_left = _val_get(ast[1])
        val_right = _val_get(ast[2])
        if isinstance(val_right, ( dict, list, set, tuple )):
            # FIELD-A is listed in FIELD-B, which is an iterable
            return val_left in val_right
        # SUBSTRING: VALUE in FIELD, which is a scalar
        return val_left in val_right
    elif ast[0] == "exists":
        return True if ast_sym(ast[1], env) else False
    elif ast[0] == ":":
        value = ast_sym(ast[1], env)
        if not isinstance(value, str):
            # not an scalar value, happens when we ask for a field
            # that is a nested dictionary, for example -- so let's
            # just encode it
            value = str(value)
        # ast[2] is what we are looking for; : is always treating it
        # as a regex, so we need to compile it; note re.compile()
        # caches the compiled regex, so we don't need to worry about
        # recompiling taking too long for repeated calls and this code
        # is simpler--could argue we could precompile somewhere in the
        # analysis phase, FIXME: exercise for the reader who has time
        return True if re.compile(ast[2]).search(value) else False

_mutex = threading.Lock()



def precompile(expr_text: str):
    """
    Compile a parser expression and return an AST object for it

    :param str expr_text: string with the expression text, eg:

      >>> ast = commonl.expr_parser.compile('symbol1 == "ef34" and symbol2 < 3')

    :returns: AST object for the given expression
    """
    with _mutex:		# the parser is not reentrant
        return parser.parse(expr_text)



def symbol_list(ast: tuple, _l = None):
    """
    Given a compiled AST expression, return the list of symbols it contains

    :param tuple ast: ast expression returned by :func:`compile`

    >>> ast = commonl.expr_parser.parse("(( var1 )  and ( var2 or level > 3 ) )")
    >>> print(ast)
    ('and', ('exists', 'var1'), ('or', ('exists', 'var2'), ('>', 'level', 3)))
    >>> symbols = commonl.expr_parser.symbol_list(ast)
    >>> print(symbols)
    [ 'var1', 'var2', 'level' ]
    """
    assert isinstance(ast, tuple)
    if _l == None:
        _l = []

    if len(ast) == 1:
        return _l
    operator = ast[0]
    count = 1
    for symbol in ast[1:]:
        if isinstance(symbol, str):
            # in is slightly special FIELD in DICTFIELD
            if operator == "in":
                _l.append(symbol)
            elif count == 1:
                # other operators only the first field is a symbol
                _l.append(symbol)
        if isinstance(symbol, tuple):
            symbol_list(symbol, _l)
        count += 1

    return _l



def parse(expr_text: str, env: dict, ast: tuple = None):
    """
    Given a text representation of an expression in our language,
    use the provided environment to determine whether the expression
    is true or false

    :param str expr_text: string with the expression text, eg:

      >>> ast = commonl.expr_parser.compile('symbol1 == "ef34" and symbol2 < 3')

    :param dict env: dictionary keyed by string of symbols and their
      values, eg

      >>> env = { "symbol1": "ef34", "symbol2": 3 }
    """
    commonl.assert_dict_key_strings(env, env)
    # Like it's C counterpart, state machine is not thread-safe
    if ast == None:
        ast = precompile(expr_text)
    return ast_expr(ast, env)



# Just some test code
if __name__ == "__main__":

    local_env = {
        "A" : "1",
        "A.there" : "3",
        "A.not_there" : "z",
        "C" : "foo",
        "D" : "20",
        "E" : 0x100,
        "F" : "baz",
        "N5" : 5,
        "type" : "arduino101",
        "quark_se_stub" : "yes",
        "bsp_model" : "arc",
        "value_list" : [ "1", "2", "3" ],
        "value_dict" : { "1": 1, "2": 2, "3": 3 },
        "list_of_things" : [ 1, 2, 3, "string1", "string2" ],
    }

    for line, expected in [
            (
                "A.3 == 3 and type == \"arduino101\" and quark_se_stub == 'yes' and bsp_model == 'arc' ",
                # shall fail because there is no A.3
                False,
            ),
            (
                "A.there == '3' and type == \"arduino101\" and quark_se_stub == 'yes' and bsp_model == 'arc' ",
                True,
            ),
            # shall fail because there is no A.3
            ( "A.3 in [ 1, 2, 3 ]", False ),
            ( "A.there in value_list", True ),
            ( "A.not_there in value_list", False ),
            ( "not E in list_of_things", True ),
            ( "A.there in value_dict", True ),
            ( "A.not_there in value_dict",  False ),
            ( '"string1" in list_of_things', True ),
            ( '"string3" in list_of_things', False ),
            ( '1 in list_of_things', True ),
            ( '4 in list_of_things', False ),
            ( 'N5 < 4', False ),
    ]:
        print("\n\nProcessing: ", line)
        lex.input(line)
        for tok in iter(lex.token, None):
            print("TOKEN", tok.type, tok.value)
        print("PARSE TREE", parser.parse(line))
        result = parse(line, local_env)
        if expected != result:
            print("FAIL: expected %s, got %s" % (expected, result))
        else:
            print("OK")


