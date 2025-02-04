#!/usr/bin/python

#
# Copyright (c) 2008 Michael Eddington
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

# Authors:
#   Frank Laub (frank.laub@gmail.com)
#   Michael Eddington (mike@phed.org)

# $Id$


import re
import pprint
import spark

def __private():
	class Token:
		def __init__(self, type, value=None):
			self.type = type
			self.value = value
		def __cmp__(self, o):
			return cmp(self.type, o)
		def __repr__(self):
			return self.value or self.type

	class AST:
		def __init__(self, type):
			self.type = type
			self._kids = []
		def __getitem__(self, i):
			return self._kids[i]
		def __len__(self):
			return len(self._kids)
		def __setslice__(self, low, high, seq):
			self._kids[low:high] = seq
		def __cmp__(self, o):
			return cmp(self.type, o)

	class GdbMiScannerBase(spark.GenericScanner):
		def tokenize(self, input):
			self.rv = []
			spark.GenericScanner.tokenize(self, input)
			return self.rv

		def t_nl(self, s):
			r'\n|\r\n'
			self.rv.append(Token('nl'))

		def t_whitespace(self, s):
			r'[ \t\f\v]+'
			pass

		def t_symbol(self, s):
			r',|\{|\}|\[|\]|\='
			self.rv.append(Token(s, s))

		def t_result_type(self, s):
			r'\*|\+|\^'
			self.rv.append(Token('result_type', s))

		def t_stream_type(self, s):
			r'\@|\&|\~'
			self.rv.append(Token('stream_type', s))

		def t_string(self, s):
			r'[\w-]+'
			self.rv.append(Token('string', s))

		def t_c_string(self, s):
			r'\".*?(?<![\\\\])\"'
			inner = self.__unescape(s[1:len(s)-1])
			self.rv.append(Token('c_string', inner))

		def t_default(self, s):
			r'( . | \n )+'
			raise Exception("Specification error: unmatched input for '%s'" % s)

		def __unescape(self, s):
			s = re.sub(r'\\r', r'\r', s)
			s = re.sub(r'\\n', r'\n', s)
			s = re.sub(r'\\t', r'\t', s)
			return re.sub(r'\\(.)', r'\1', s)


	class GdbMiScanner(GdbMiScannerBase):
		def t_token(self, s):
			r'\d+'
			self.rv.append(Token('token', s))

	class GdbMiParser(spark.GenericASTBuilder):
		def __init__(self):
			spark.GenericASTBuilder.__init__(self, AST, 'output')

		def p_output(self, args):
			'''
				output ::= record_list
				record_list ::= generic_record
				record_list ::= generic_record record_list
				generic_record ::= result_record
				generic_record ::= stream_record
				result_record ::= result_header result_list nl
				result_record ::= result_header nl
				result_header ::= token result_type class
				result_header ::= result_type class
				result_header ::= token = class
				result_header ::= = class
				stream_record ::= stream_type c_string nl
				result_list ::= , result result_list
				result_list ::= , result
				result_list ::= , tuple
				result ::= variable = value
				class ::= string
				variable ::= string
				value ::= const
				value ::= tuple
				value ::= list
				value_list ::= , value
				value_list ::= , value value_list
				const ::= c_string
				tuple ::= { }
				tuple ::= { result }
				tuple ::= { result result_list }
				list ::= [ ]
				list ::= [ value ]
				list ::= [ value value_list ]
				list ::= [ result ]
				list ::= [ result result_list ]
				list ::= { value }
				list ::= { value value_list }
			'''
			pass

		def terminal(self, token):
			#  Homogeneous AST.
			rv = AST(token.type)
			rv.value = token.value
			return rv

		def nonterminal(self, type, args):
			#  Flatten AST a bit by not making nodes if there's only one child.
			exclude = [
				'record_list'
			]
			if len(args) == 1 and type not in exclude:
				return args[0]
			return spark.GenericASTBuilder.nonterminal(self, type, args)

		def error(self, token, i=0, tokens=None):
			if i > 2:
				print('%s %s %s %s' % (tokens[i-3], tokens[i-2], tokens[i-1], tokens[i]))
			raise Exception("Syntax error at or near %d:'%s' token" % (i, token))

	class GdbMiInterpreter(spark.GenericASTTraversal):
		def __init__(self, ast):
			spark.GenericASTTraversal.__init__(self, ast)
			self.postorder()

		def __translate_type(self, type):
			table = {
				'^': 'result',
				'=': 'notify',
				'+': 'status',
				'*': 'exec',
				'~': 'console',
				'@': 'target',
				'&': 'log'
			}
			return table[type]

		def n_result(self, node):
			# result ::= variable = value
			node.value = { node[0].value: node[2].value }
			#print('result: %s' % node.value)

		def n_tuple(self, node):
			if len(node) == 2:
				# tuple ::= {}
				node.value = {}
			elif len(node) == 3:
				# tuple ::= { result }
				node.value = node[1].value
			elif len(node) == 4:
				# tuple ::= { result result_list }
				node.value = node[1].value
				for result in node[2].value:
					for n, v in result.items():
						if node.value.has_key(n):
							#print('**********list conversion: [%s] %s -> %s' % (n, node.value[n], v))
							old = node.value[n]
							if not isinstance(old, list):
								node.value[n] = [ node.value[n] ]
							node.value[n].append(v)
						else:
							node.value[n] = v
			else:
				raise Exception('Invalid tuple')
			#print('tuple: %s' % node.value)

		def n_list(self, node):
			if len(node) == 2:
				# list ::= []
				node.value = []
			elif len(node) == 3:
				# list ::= [ value ]
				node.value = [ node[1].value ]
			elif len(node) == 4:
				# list ::= [ value value_list ]
				node.value = [ node[1].value ] + node[2].value
				#list ::= [ result ]
				#list ::= [ result result_list ]
				#list ::= { value }
				#list ::= { value value_list }
			#print('list %s' % node.value)

		def n_value_list(self, node):
			if len(node) == 2:
				#value_list ::= , value
				node.value = [ node[1].value ]
			elif len(node) == 3:
				#value_list ::= , value value_list
				node.value = [ node[1].value ] + node[2].value

		def n_result_list(self, node):
			if len(node) == 2:
				# result_list ::= , result
				node.value = [ node[1].value ]
			else:
				# result_list ::= , result result_list
				node.value = [ node[1].value ] + node[2].value
			#print('result_list: %s' % node.value)

		def n_result_record(self, node):
			node.value = node[0].value
			if len(node) == 3:
				# result_record ::= result_header result_list nl
				node.value['results'] = node[1].value
			elif len(node) == 2:
				# result_record ::= result_header nl
				pass
			#print('result_record: %s' % (node.value))

		def n_result_header(self, node):
			if len(node) == 3:
				# result_header ::= token result_type class
				node.value = {
					'token': node[0].value,
					'type': self.__translate_type(node[1].value),
					'class_': node[2].value,
					'record_type': 'result'
				}
			elif len(node) == 2:
				# result_header ::= result_type class
				node.value = {
					'token': None,
					'type': self.__translate_type(node[0].value),
					'class_': node[1].value,
					'record_type': 'result'
				}

		def n_stream_record(self, node):
			# stream_record ::= stream_type c_string nl
			node.value = {
				'type': self.__translate_type(node[0].value),
				'value': node[1].value,
				'record_type': 'stream'
			}
			#print('stream_record: %s' % node.value)

		def n_record_list(self, node):
			if len(node) == 1:
				# record_list ::= generic_record
				node.value = [ node[0].value ]
			elif len(node) == 2:
				# record_list ::= generic_record record_list
				node.value = [ node[0].value ] + node[1].value
			#print('record_list: %s' % node.value)

		#def default(self, node):
			#print('default: ' + node.type)

	class GdbDynamicObject:
		def __init__(self, dict_):
			self.graft(dict_)

		def __repr__(self):
			return pprint.pformat(self.__dict__)

		def __nonzero__(self):
			return len(self.__dict__) > 0

		def __getitem__(self, i):
			if i == 0 and len(self.__dict__) > 0:
				return self
			else:
				raise IndexError

		def __getattr__(self, name):
			if name.startswith('__'):
				raise AttributeError
			return None

		def graft(self, dict_):
			for name, value in dict_.items():
				name = name.replace('-', '_')
				if isinstance(value, dict):
					value = GdbDynamicObject(value)
				elif isinstance(value, list):
					x = value
					value = []
					for item in x:
						if isinstance(item, dict):
							item = GdbDynamicObject(item)
						value.append(item)
				setattr(self, name, value)

	class GdbMiRecord:
		def __init__(self, record):
			self.result = None
			for name, value in record[0].items():
				name = name.replace('-', '_')
				if name == 'results':
					for result in value:
						if not self.result:
							self.result = GdbDynamicObject(result)
						else:
							# graft this result to self.results
							self.result.graft(result)
				else:
					setattr(self, name, value)

		def __repr__(self):
			return pprint.pformat(self.__dict__)

	return (GdbMiScanner(), GdbMiParser(), GdbMiInterpreter, GdbMiRecord)

(__the_scanner, __the_parser, __the_interpreter, __the_output) = __private()

def scan(input):
	return __the_scanner.tokenize(input)

def parse(tokens):
	return __the_parser.parse(tokens)

def process(input):
	tokens = scan(input)
	ast = parse(tokens)
	__the_interpreter(ast)
	return __the_output(ast.value)

if __name__ == '__main__':
	def main():
		def print_tokens(tokens):
			print
			for token in tokens:
				if token.value:
					print(token.type + ': ' + token.value)
				else:
					print(token.type)

		def run_test(test):
			lines = test.splitlines()
			for line in lines:
				tokens = scan(line + '\n')
				#print_tokens(tokens)

				ast = parse(tokens)
				__the_interpreter(ast)
				output = __the_output(ast.value)
				print(output)

		x = '"No symbol table is loaded.  Use the \\"file\\" command."'
		m = re.match('\".*?(?<![\\\\])\"', x)
		z = x[m.start():m.end()]

		test1 = '22^done,time={wallclock="0.05395",user="0.02996",system="0.02222",start="1210321030.972724",end="1210321031.026675"}\n'
		test2 = '''~"[Switching to process 3832 local thread 0x3607]\\n"
=shlibs-updated
^running
'''

		test3 = '''=shlibs-added,shlib-info={num="2",name="qi",kind="-",dyld-addr="0x1000",reason="exec",requested-state="Y",state="Y",path="/Users/franklaub/bin/qi",description="/Users/franklaub/bin/qi",loaded_addr="",slide="0x0",prefix="",dsym-objpath="/Users/franklaub/bin/qi.dSYM/Contents/Resources/DWARF/qi"},time={now="1210290757.432413"}
=shlibs-added,shlib-info={num="3",name="libgcc_s.1.dylib",kind="-",dyld-addr="0x9230a000",reason="dyld",requested-state="Y",state="Y",path="/usr/lib/libgcc_s.1.dylib",description="/usr/lib/libgcc_s.1.dylib",loaded_addr="0x9230a000",slide="-0x6dcf6000",prefix=""},time={now="1210290757.432771"}
=shlibs-added,shlib-info={num="4",name="libSystem.B.dylib",kind="-",dyld-addr="0x950aa000",reason="dyld",requested-state="Y",state="Y",path="/usr/lib/libSystem.B.dylib",description="/usr/lib/libSystem.B.dylib",loaded_addr="0x950aa000",slide="-0x6af56000",prefix="",commpage-objpath="/usr/lib/libSystem.B.dylib[LC_SEGMENT.__DATA.__commpage]"},time={now="1210290757.433091"}
=shlibs-added,shlib-info={num="5",name="libmathCommon.A.dylib",kind="-",dyld-addr="0x95018000",reason="dyld",requested-state="Y",state="Y",path="/usr/lib/system/libmathCommon.A.dylib",description="/usr/lib/system/libmathCommon.A.dylib",loaded_addr="0x95018000",slide="-0x6afe8000",prefix=""},time={now="1210290757.433390"}
*stopped,time={wallclock="1.02740",user="0.00379",system="0.00791",start="1210290756.408774",end="1210290757.436179"},reason="breakpoint-hit",commands="no",times="1",bkptno="1",thread-id="1"
'''

		test4 = '''=shlibs-added,shlib-info={num="2",name="qi",kind="-",dyld-addr="0x1000",reason="exec",requested-state="Y",state="Y",path="/Users/franklaub/bin/qi",description="/Users/franklaub/bin/qi",loaded_addr="",slide="0x0",prefix="",dsym-objpath="/Users/franklaub/bin/qi.dSYM/Contents/Resources/DWARF/qi"},time={now="1210290757.432413"}
^running
'''
		test5 = '''=class,variable={frame={x="2"},frame={x="2"}, regs={"1","2","3"}}
^running
'''
		test6 = '10^done,stack-args={frame={level="0",args={}}},time={wallclock="0.00006",user="0.00004",system="0.00002",start="1210530442.460765",end="1210530442.460825"}\n'

		run_test(test1)
		run_test(test2)
		run_test(test3)
		run_test(test4)
		run_test(test5)
		run_test(test6)

	main()
