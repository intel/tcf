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
"""
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
               | string

When symbols are encountered, they are looked up in an environment
dictionary supplied to the parse() function.

For the case where

    expression ::= symbol

it evaluates to true if the symbol is defined to a non-empty string.

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
import re
import threading

import ply.lex as lex
import ply.yacc as yacc

reserved = {
    'and' : 'AND',
    'or' : 'OR',
    'not' : 'NOT',
    'in' : 'IN',
}

tokens = [
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
    """const : STR
             | number"""
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
        else:
            return str(env[ast])
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
            if isinstance(val, _t_symbol_c):
                return ast_sym(val, env)
            else:
                return val
        return _val_get(ast[1]) in _val_get(ast[2])
    elif ast[0] == "exists":
        return True if ast_sym(ast[1], env) else False
    elif ast[0] == ":":
        return True if re.compile(ast[2]).search(ast_sym(ast[1], env)) else False

mutex = threading.Lock()

def parse(expr_text, env):
    """Given a text representation of an expression in our language,
    use the provided environment to determine whether the expression
    is true or false"""

    # Like it's C counterpart, state machine is not thread-safe
    mutex.acquire()
    try:
        ast = parser.parse(expr_text)
    finally:
        mutex.release()

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


