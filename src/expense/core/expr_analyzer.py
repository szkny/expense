import re
import ast
import copy


# 安全に括弧内の単純な足し算/引き算だけ評価する関数
def safe_eval_add_sub(node):
    if isinstance(node, ast.Expression):
        return safe_eval_add_sub(node.body)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int,)):
            raise ValueError("非整数は扱わない")
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -safe_eval_add_sub(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left = safe_eval_add_sub(node.left)
        right = safe_eval_add_sub(node.right)
        return left + right if isinstance(node.op, ast.Add) else left - right
    raise ValueError("許可されていない式です（加算/減算以外が含まれます）")


# 括弧内の「足し算／引き算だけ」のものを評価してプレースホルダに置き換える
def replace_parenthetical_additions(expr):
    placeholders = {}
    counter = 0

    # innermost の括弧から繰り返し処理
    while True:
        changed = False

        def repl(m):
            nonlocal counter, changed
            inner = m.group(0)[1:-1]  # 括弧を除いた中身
            # '*' や '/' が含まれていたら評価しない（掛け算などがある場合はそのまま）
            if "*" in inner or "/" in inner:
                return m.group(0)
            # 試しに AST で解析して加減算のみかをチェックして評価
            try:
                node = ast.parse(inner, mode="eval")
                val = safe_eval_add_sub(node)
            except Exception:
                return m.group(0)
            # 評価できたらプレースホルダに置換（後で AST 中の Name を Constant に置換）
            name = f"__P{counter}__"
            placeholders[name] = val
            counter += 1
            changed = True
            return name

        new_expr = re.sub(r"\([^()]*\)", repl, expr)
        expr = new_expr
        if not changed:
            break

    return expr, placeholders


# プレースホルダ Name -> Constant(value) に置換（置換した Constant に _is_paren 属性を付ける）
class PlaceholderReplacer(ast.NodeTransformer):
    def __init__(self, mapping):
        self.mapping = mapping

    def visit_Name(self, node):
        if node.id in self.mapping:
            new = ast.copy_location(ast.Constant(self.mapping[node.id]), node)
            # どの定数が「元々括弧だった」かを示すフラグ
            setattr(new, "_is_paren", True)
            return new
        return node


# 掛け算を「加算の繰り返し」に展開する Transformer
class MulExpander(ast.NodeTransformer):
    MAX_REPEAT = 500  # 安全のための上限（必要なら調整してください）

    def visit_BinOp(self, node):
        # 先に子ノードを処理
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)

        if isinstance(node.op, ast.Mult):
            left = node.left
            right = node.right
            left_paren = getattr(left, "_is_paren", False)
            right_paren = getattr(right, "_is_paren", False)

            times = None
            multiplicand = None

            # どちらが括弧由来かで優先を決める（括弧由来があればそれを multiplicand にする）
            if left_paren and not right_paren:
                multiplicand = left
                if isinstance(right, ast.Constant) and isinstance(
                    right.value, int
                ):
                    times = right.value
            elif right_paren and not left_paren:
                multiplicand = right
                if isinstance(left, ast.Constant) and isinstance(
                    left.value, int
                ):
                    times = left.value
            else:
                # 括弧情報が無ければ、定数側を times にする（片方が定数ならそれが回数）
                if isinstance(left, ast.Constant) and not isinstance(
                    right, ast.Constant
                ):
                    if isinstance(left.value, int):
                        times = left.value
                        multiplicand = right
                elif isinstance(right, ast.Constant) and not isinstance(
                    left, ast.Constant
                ):
                    if isinstance(right.value, int):
                        times = right.value
                        multiplicand = left
                elif isinstance(left, ast.Constant) and isinstance(
                    right, ast.Constant
                ):
                    # 両方定数の場合は右側を回数とみなす（= 120*3 -> 120 を 3 回）
                    if isinstance(right.value, int):
                        times = right.value
                        multiplicand = left

            # 展開条件チェック
            if times is None or multiplicand is None:
                return node  # 展開しない（非整数回数や不明な場合）

            if not isinstance(times, int) or times < 0:
                return node

            if times > self.MAX_REPEAT:
                # 安全機構: 大きすぎる回数は展開しない（必要なら MAX_REPEAT を引き上げてください）
                return node

            # multiplicand を times 回繰り返した加算式を作る
            new_expr = None
            for i in range(times):
                part = copy.deepcopy(multiplicand)
                new_expr = (
                    part
                    if new_expr is None
                    else ast.BinOp(left=new_expr, op=ast.Add(), right=part)
                )

            return new_expr

        return node


def expand_multiplication(expr: str) -> str:
    prefix = ""
    if expr.startswith("="):
        prefix = "="
        expr = expr[1:]

    # 1) 括弧内の単純な加減算だけ評価してプレースホルダに置換
    transformed, placeholders = replace_parenthetical_additions(expr)

    # 2) AST にしてプレースホルダを Constant に戻しつつ _is_paren フラグを付ける
    tree = ast.parse(transformed, mode="eval")
    tree = PlaceholderReplacer(placeholders).visit(tree)
    ast.fix_missing_locations(tree)

    # 3) 掛け算を展開
    tree = MulExpander().visit(tree)
    ast.fix_missing_locations(tree)

    # 4) 文字列に戻す
    result = ast.unparse(tree).replace("(", "").replace(")", "")
    return prefix + result
