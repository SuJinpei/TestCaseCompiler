import ply.lex as lex
import ply.yacc as yacc
import sys


if len(sys.argv) != 2:
    print("Usage:", sys.argv[0], "test_case_file")
    exit()

case_file = open(sys.argv[1])
text = case_file.read()


reserved_key_words = {
    'Async': 'Async',
    'if': 'IF',
    'then': 'THEN',
    'else': 'ELSE',
    'while': 'WHILE',
    'TestCase': 'TestCase',
    'Terminal': 'Terminal',
    'ResultSet': 'ResultSet',
    'expect_equal': 'ExpectEqual',
    'expect_not_equal': 'ExpectNotEqual',
    'expect_str_equal': 'ExpectStrEqual',
    'expect_str_not_equal': 'ExpectStrNotEqual',
    'expect_substr': 'ExpectSubStr',
    'expect_no_substr': 'ExpectNoSubStr',
    'expect_in': 'ExpectIn',
    'expect_not_in': 'ExpectNotIn',
    'Config': 'Config'
}

tokens = [
    "RawString",
    "NormalString",
    "Number",
    "LBrace",
    "RBrace",
    "Colon",
    "Comma",
    "Semicolon",
    "EqualSign",
    "LParenthesis",
    "RParenthesis",
    "ID"
] + list(reserved_key_words.values())


def t_RawString(t):
    r"""\"\"\".*\"\"\""""
    t.lexer.lineno += t.value.count('\n')
    return t


def t_NormalString(t):
    r"""\"([^\\\"]|\\\")*\""""
    return t

t_Number = r"\d+(\.\d+)?"
t_LBrace = r"{"
t_RBrace = r"}"
t_Colon = r"\:"
t_Comma = r","
t_Semicolon = r";"
t_EqualSign = r"="
t_LParenthesis = r"\("
t_RParenthesis = r"\)"

t_ignore = " \t"
t_ignore_comment = r"\#.*"


def t_ID(t):
    r"""[a-zA-Z_][a-zA-Z0-9_]*"""
    t.type = reserved_key_words.get(t.value, 'ID')
    return t


def t_newline(t):
    r"""\n+"""
    t.lexer.lineno += len(t.value)


# Compute column.
#     cases_text is the cases text string
#     token is a token instance
def find_column(cases_text, token):
    line_start = cases_text.rfind('\n', 0, token.lexpos) + 1
    return (token.lexpos - line_start) + 1


def print_code_fragment(t):
    max_pos = len(text) - 1
    fragment_start = text.rfind('\n', 0, t.lexpos)
    fragment_end = text.find('\n', t.lexpos, max_pos)

    if fragment_start < 0:
        fragment_start = 0

    if fragment_end < 0:
        fragment_end = max_pos

    sys.stderr.write("[Cases Code Fragment]\n...%s\n" % (text[fragment_start:fragment_end]))
    sys.stderr.write("%s^\n...\n" % (" " * (find_column(text, t) + 1)))


def t_error(t):
    sys.stderr.write("[Lex Error] Line:%s,Column:%s\n" % (t.lineno, find_column(text, t)))
    print_code_fragment(t)


lexer = lex.lex()


case_name = ""
line_offset = 0
output_file = open("real_test.py", mode="w", encoding="utf-8")
inner_case_seq = 1


def p_spec(p):
    r"""Spec : Configuration Cases"""
    output_file.write("""
if __name__ == '__main__':
    unittest.main()
""")


def p_configuration(p):
    r"""Configuration : Config LBrace String RBrace"""

    output_file.write("# -*- coding: utf-8 -*-\n")

    output_file.write("""
import threading
import time
import queue
import pdbc.trafodion.connector as connector
import unittest
import traceback""")

    output_file.write("\n\nconfig = {%s}" % (p[3][3:len(p[3]) - 4]))
    output_file.write("""


class QueryTerminal (threading.Thread):

    def __init__(self, auto_commit=True):
        super(QueryTerminal, self).__init__()
        try:
            self.connection = connector.connect(**config)
            self.connection.set_auto_commit(auto_commit)
            self.cursor = self.connection.cursor()
            self.stored_result_dict = {}
        except Warning as w:
            print("Connection Warning: ", w)
        except Exception as e:
            print("Connection Exception: ", e)

        # item of queue is a list
        # list idx 0: task type [0 close, 1 execute query, 2 fetch result]
        # list idx 1: task text
        # list idx 2: additional control info [0 nothing]
        self.task_queue = queue.Queue(20)

        # 0 not start, 1 waiting input, 2 executing, 3 down
        self.status = 0

        # idx 0: last execution return code, 0 success, 1 warning, 2 error
        # idx 1: last error or warning message if exists
        self.last_execution_result = [0, ""]

    def run(self):
        while True:
            self.status = 1
            query = self.task_queue.get()

            if query[0] == 0:
                self.status = 3
                self.cursor.close()
                self.connection.close()
                break

            try:
                if query[0] == 1:
                    self.status = 2
                    self.reset_result()
                    print("[INFO] execute query:", query[1])
                    time_start = time.time()
                    self.cursor.execute(query[1])
                    time_end = time.time()
                    print("[INFO]success after ", round(time_end - time_start, 3), "s")

                if query[0] == 2:
                    print("[INFO] fetch result")
                    time_start = time.time()
                    self.stored_result_dict[query[1]] = self.cursor.fetchall()
                    time_end = time.time()
                    print("[INFO] success after ", round(time_end - time_start, 3), "s")

            except connector.Warning as w:
                print("query:", query[1], w)
                self.last_execution_result = [1, w]
            except connector.Error as e:
                print("query:", query[1], e)
                self.last_execution_result = [2, e]

            self.task_queue.task_done()

    def close(self):
        self.task_queue.put([0, "shut down", 0])

    def reset_result(self):
        self.last_execution_result = [0, ""]

    def store_result(self, name):
        self.stored_result_dict[name] = "not ready"
        self.task_queue.put([2, name, 0])

    def get_result_set(self, name):
        for row in self.stored_result_dict[name]:
            print(row)
        return self.stored_result_dict[name]

    def get_last_ret_code(self):
        return self.last_execution_result[0]

    def execute(self, query):
        self.task_queue.put([1, query, 0])

    def wait_finish(self):
        self.task_queue.join()


class MyTestCase (unittest.TestCase):
""")


def p_cases_cases(p):
    r"""Cases : Cases Case"""
    pass


def p_cases_case(p):
    r"""Cases : Case"""
    pass


def p_case(p):
    r"""Case : TestCase CaseName CaseStart Statements CaseEnd"""
    pass


def p_case_name(p):
    r"""CaseName : ID"""
    global case_name
    case_name = p[0] = p[1]


def p_case_start(p):
    r"""CaseStart : LBrace"""
    global line_offset, inner_case_seq
    line_offset = 4
    output_file.write("\n%sdef test_%s_%s(self):\n" % (" " * line_offset, inner_case_seq, case_name))
    inner_case_seq += 1
    line_offset += 4
    output_file.write("%sterminals = []\n" % (" " * line_offset))
    output_file.write("%stry:\n" % (" " * line_offset))
    line_offset += 4
    output_file.write("%scase_terminal = QueryTerminal()\n" % (" " * line_offset))
    output_file.write("%scase_terminal.start()\n" % (" " * line_offset))
    output_file.write("%sterminals.append(case_terminal)\n" % (" " * line_offset))


def p_statements_statements(p):
    r"""Statements : Statements Statement"""
    pass


def p_statements_statement(p):
    r"""Statements : Statement"""
    pass


def p_statement(p):
    r"""Statement : StatementBody Semicolon"""
    pass


def p_statement_body_query(p):
    r"""StatementBody : ScopedStatement"""
    pass


def p_scoped_statement_no_term(p):
    r"""ScopedStatement : Colon ScopedStatementBody"""
    output_file.write("%scase_terminal.execute(%s)\n" % (" " * line_offset, p[2][1]))
    if p[2][0]:
        output_file.write("%scase_terminal.store_result(\"result\")\n" % (" " * line_offset))
    output_file.write("%scase_terminal.wait_finish()\n" % (" " * line_offset))
    p[0] = ("case_terminal", (p[2][0], "result"))


def p_scoped_statement_body_query(p):
    r"""ScopedStatementBody : Query"""
    # (False, query): just execute, needn't to fetch result.
    p[0] = (False, p[1])


def p_query(p):
    r"""Query : String"""
    p[0] = p[1]


def p_string_normal(p):
    r"""String : NormalString"""
    p[0] = p[1]


def p_string_raw(p):
    r"""String : RawString"""
    p[0] = p[1]


def p_scoped_statement_result_set_query(p):
    r"""ScopedStatementBody : ResultSetQuery"""
    p[0] = p[1]


def p_result_set_query(p):
    r"""ResultSetQuery : ResultSet LParenthesis Query RParenthesis"""
    # (True, query): query need store result set
    p[0] = (True, p[3])


def p_scoped_statement_no_term_async(p):
    r"""ScopedStatement : Async Colon ScopedStatementBody"""
    output_file.write("%scase_terminal.execute(%s)\n" % (" " * line_offset, p[2][1]))
    if p[2][0]:
        output_file.write("%scase_terminal.store_result(\"result\")\n" % (" " * line_offset))
    p[0] = ("case_terminal", (p[2][0], "result"))


def p_scoped_statement_with_term(p):
    r"""ScopedStatement : Term Colon ScopedStatementBody"""
    global line_offset
    # no result set
    output_file.write("%s%s.execute(%s)\n" % (" " * line_offset, p[1], p[3][1]))
    if p[3][0]:
        output_file.write("%s%s.store_result(\"scope_term_result\")\n" % (" " * line_offset, p[1]))
    output_file.write("%s%s.wait_finish()\n" % (" " * line_offset, p[1]))
    p[0] = (p[1], (p[3][0], "scope_term_result"))


def p_term(p):
    r"""Term : ID"""
    p[0] = p[1]


def p_scoped_statement_with_term_async(p):
    r"""ScopedStatement : Async Term Colon ScopedStatementBody"""
    output_file.write("%s%s.execute(%s)\n" % (" " * line_offset, p[2], p[4]))
    if p[4][0]:
        output_file.write("%s%s.store_result(\"scope_term_result\")\n" % (" " * line_offset, p[2]))
    p[0] = (p[2], (p[4][0], "scope_term_result"))


def p_statement_body_declaration(p):
    r"""StatementBody : Declaration"""
    pass


def p_declaration(p):
    r"""Declaration : Terminal TermList"""
    for term in p[2]:
        output_file.write("%s%s = QueryTerminal()\n" % (" " * line_offset, term))
        output_file.write("%s%s.start()\n" % (" " * line_offset, term))
        output_file.write("%sterminals.append(%s)\n" % (" " * line_offset, term))


def p_term_list_list(p):
    r"""TermList : TermList Term"""
    p[0] = p[1] + [p[2]]


def p_term_list_term(p):
    r"""TermList : Term"""
    p[0] = [p[1]]


def p_statement_body_assignment(p):
    r"""StatementBody : Assignment"""
    pass


def p_assignment_expression(p):
    r"""Assignment : Variable EqualSign Expression"""
    global line_offset
    output_file.write("%s%s = %s\n" % (" " * line_offset, p[1], p[3]))


def p_variable(p):
    r"""Variable : ID"""
    p[0] = p[1]


def p_expression_string(p):
    r"""Expression : String"""
    p[0] = p[1]


def p_expression_number(p):
    r"""Expression : Number"""
    p[0] = p[1]


def p_expression_scoped_statement(p):
    r"""Expression : ScopedStatement"""
    # ScopedStatement return (scope, (type, result_name))
    # type : False execution return code
    # type : True result set
    if p[1][1][0]:
        output_file.write("%stemp_var = %s.get_result_set(\"%s\")\n" % (" " * line_offset, p[1][0], p[1][1][1]))
    else:
        output_file.write("%stemp_var = %s.get_last_ret_code()\n" % (" " * line_offset, p[1][0]))

    p[0] = "temp_var"


def p_expression_variable(p):
    r"""Expression : Variable"""
    p[0] = p[1]


def p_statement_body_assertion(p):
    r"""StatementBody : Assertion"""
    pass


def p_assertion_expect_equal(p):
    r"""Assertion : ExpectEqual LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertEqual(%s, %s)\n" % (" " * line_offset, p[3], p[5]))


def p_assertion_expect_not_equal(p):
    r"""Assertion : ExpectNotEqual LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertNotEqual(%s, %s)\n" % (" " * line_offset, p[3], p[5]))


def p_assertion_expect_str_equal(p):
    r"""Assertion : ExpectStrEqual LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertEqual(str(%s), str(%s))\n" % (" " * line_offset, p[3], p[5]))


def p_assertion_expect_str_not_equal(p):
    r"""Assertion : ExpectStrNotEqual LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertNotEqual(str(%s), str(%s))\n" % (" " * line_offset, p[3], p[5]))


def p_assertion_expect_sub_str(p):
    r"""Assertion : ExpectSubStr LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertTrue(str(%s) in str(%s))\n" % (" " * line_offset, p[5], p[3]))


def p_assertion_expect_no_sub_str(p):
    r"""Assertion : ExpectNoSubStr LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertTrue(str(%s) not in str(%s))\n" % (" " * line_offset, p[5], p[3]))


def p_assertion_expect_in(p):
    r"""Assertion : ExpectIn LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertTrue(%s in %s)\n" % (" " * line_offset, p[5], p[3]))


def p_assertion_expect_not_in(p):
    r"""Assertion : ExpectNotIn LParenthesis Expression Comma Expression RParenthesis"""
    global line_offset
    output_file.write("%sself.assertTrue(%s not in %s)\n" % (" " * line_offset, p[5], p[3]))


def p_case_end(p):
    r"""CaseEnd : RBrace"""
    global line_offset
    line_offset -= 4

    output_file.write("%sexcept AssertionError as ae:\n" % (" " * line_offset))
    output_file.write("%s    print(\"Test Case Assertion Error: \")\n" % (" " * line_offset))
    output_file.write("%s    self.fail(ae)\n" % (" " * line_offset))
    output_file.write("%sexcept Exception as e:\n" % (" " * line_offset))
    output_file.write("%s    print(\"Test Case Exception: \")\n" % (" " * line_offset))
    output_file.write("%s    self.fail(e)\n" % (" " * line_offset))
    output_file.write("%sfinally:\n" % (" " * line_offset))
    line_offset += 4
    output_file.write("%sfor term in terminals:\n" % (" " * line_offset))
    output_file.write("%s    term.close()\n" % (" " * line_offset))
    output_file.write("%sfor term in terminals:\n" % (" " * line_offset))
    output_file.write("%s    term.join()\n" % (" " * line_offset))


def p_error(p):
    sys.stderr.write("[Parse Error][Line:%s, Column:%s]: Invalid Token:\'%s\'\n" % (p.lineno, find_column(text, p), p.value))
    print_code_fragment(p)


parser = yacc.yacc()

# parser.parse(text, debug=True)
# parser.parse(text)

lexer.input(text)

for tk in lexer:
    print(tk)
