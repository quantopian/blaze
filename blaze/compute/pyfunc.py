
from blaze.expr import (Expr, Symbol, Field, Arithmetic, Math,
        Date, Time, DateTime, Millisecond, Microsecond, broadcast, sin, cos,
        Map)
import datetime
from datashape import iscollection
import math
import toolz
import itertools


funcnames = ('func_%d' % i for i in itertools.count())

def parenthesize(s):
    if ' ' in s:
        return '(%s)' % s
    else:
        return s


def print_python(leaves, expr):
    """ Print expression to be evaluated in Python

    >>> from blaze.expr import ceil, sin

    >>> t = Symbol('t', '{x: int, y: int, z: int, when: datetime}')
    >>> print_python([t], t.x + t.y)
    ('t[0] + t[1]', {})

    Supports mathematical and datetime access

    >>> print_python([t], sin(t.x) > ceil(t.y))  # doctest: +SKIP
    ('math.sin(t[0]) > math.ceil(t[1])', {'math':<module 'math'>})
    >>> print_python([t], t.when.day + 1)
    ('t[3].day + 1', {})

    Specify leaves of the expression to control level of printing

    >>> print_python([t.x, t.y], t.x + t.y)
    ('x + y', {})

    Returns
    -------

    s: string
       A evalable string
    scope: dict
       A namespace to add to be given to eval
    """

    if isinstance(expr, (datetime.datetime, datetime.date)):
        return repr(expr), {'datetime': datetime}
    if not isinstance(expr, Expr):
        return repr(expr), {}
    if any(expr.isidentical(leaf) for leaf in leaves):
        return expr._name, {}
    if isinstance(expr, Symbol):
        return expr._name, {}
    if isinstance(expr, Field):
        child, scope = print_python(leaves, expr._child)
        index = expr._child.fields.index(expr._name)
        return '%s[%d]' % (parenthesize(child), index), scope
    if isinstance(expr, Arithmetic):
        lhs, left_scope = print_python(leaves, expr.lhs)
        rhs, right_scope = print_python(leaves, expr.rhs)
        return ('%s %s %s' % (parenthesize(lhs),
                             expr.symbol,
                             parenthesize(rhs)),
                toolz.merge(left_scope, right_scope))
    if isinstance(expr, Math):
        child, scope = print_python(leaves, expr._child)
        return ('math.%s(%s)' % (type(expr).__name__, child),
                toolz.merge(scope, {'math': math}))
    if isinstance(expr, Date):
        child, scope = print_python(leaves, expr._child)
        return ('%s.date()' % parenthesize(child), scope)
    if isinstance(expr, Time):
        child, scope = print_python(leaves, expr._child)
        return ('%s.time()' % parenthesize(child), scope)
    if isinstance(expr, Millisecond):
        child, scope = print_python(leaves, expr._child)
        return ('%s.microsecond // 1000()' % parenthesize(child), scope)
    if isinstance(expr, DateTime):
        child, scope = print_python(leaves, expr._child)
        attr = type(expr).__name__.lower()
        return ('%s.%s' % (parenthesize(child), attr), scope)
    if isinstance(expr, Map):
        child, scope = print_python(leaves, expr._child)
        funcname = next(funcnames)
        return ('%s(%s)' % (funcname, child),
                toolz.assoc(scope, funcname, expr.func))
    raise NotImplementedError()


def funcstr(leaves, expr):
    """ Lambda string for an expresion

    >>> t = Symbol('t', '{x: int, y: int, z: int, when: datetime}')

    >>> funcstr([t], t.x + t.y)
    ('lambda t: t[0] + t[1]', {})

    >>> funcstr([t.x, t.y], t.x + t.y)
    ('lambda x, y: x + y', {})

    Also returns scope for libraries like math or datetime

    >>> funcstr([t.x, t.y], sin(t.x) + t.y)  # doctest: +SKIP
    ('lambda x, y: math.sin(x) + y', {'math': <module 'math'>})
    """
    result, scope = print_python(leaves, expr)

    leaf_names = [print_python([leaf], leaf)[0] for leaf in leaves]

    return 'lambda %s: %s' % (', '.join(leaf_names),
                              result), scope


def lambdify(leaves, expr):
    """ Lambda for an expresion

    >>> t = Symbol('t', '{x: int, y: int, z: int, when: datetime}')
    >>> f = lambdify([t], t.x + t.y)
    >>> f((1, 10, 100, ''))
    11

    >>> f = lambdify([t.x, t.y, t.z, t.when], t.x + cos(t.y))
    >>> f(1, 0, 100, '')
    2.0
    """
    s, scope = funcstr(leaves, expr)
    return eval(s, scope)


Broadcastable = (Arithmetic, Math, Map, Field, DateTime)
WantToBroadcast = (Arithmetic, Math, Map, DateTime)


def broadcast_collect(expr, Broadcastable=Broadcastable,
        WantToBroadcast=WantToBroadcast):
    """ Collapse expression down using Broadcast - Tabular cases only

    Expressions of type Broadcastables are swallowed into Broadcast
    operations

    >>> t = Symbol('t', 'var * {x: int, y: int, z: int, when: datetime}')
    >>> expr = (t.x + 2*t.y).distinct()

    >>> broadcast_collect(expr)
    distinct(Broadcast(_children=(t,), _scalars=(t,), _scalar_expr=t.x + (2 * t.y)))
    """
    if (isinstance(expr, WantToBroadcast) and
        iscollection(expr.dshape)):
        leaves = leaves_of_type(Broadcastable, expr)
        expr = broadcast(expr, sorted(leaves, key=str))

    # Recurse down
    children = [broadcast_collect(i, Broadcastable, WantToBroadcast)
            for i in expr._inputs]
    return expr._subs(dict(zip(expr._inputs, children)))


@toolz.curry
def leaves_of_type(types, expr):
    """ Leaves of an expression skipping all operations of type ``types``
    """
    if not isinstance(expr, types):
        return set([expr])
    else:
        return set.union(*map(leaves_of_type(types), expr._inputs))
