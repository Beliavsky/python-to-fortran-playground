// Curated copies/adaptations, checked against the pinned transpiler by tests.
// Nothing is fetched from upstream when a user loads an example.
const example = (title, category, description, upstream, source, random = false) =>
  ({title, category, description, upstream, source, random});
export const pythonExamples = {
  sum: example('Sum of squares', 'Basics', 'An integer accumulator and a counted loop.', null,
    'total = 0\nfor i in range(1, 11):\n    total += i * i\nprint(total)\n'),
  function: example('Annotated numerical function', 'Basics', 'Explicit scalar types make the procedure interface clear.', null,
    'def square(x: float) -> float:\n    return x * x\n\nprint(square(1.5))\nprint(square(3.0))\n'),
  gcd: example('Greatest common divisor', 'Basics', 'Euclidean algorithm with integer arguments.', 'xgcd.py', `def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return a

print(gcd(12, 18))
print(gcd(1071, 462))
`),
  primes: example('Count primes', 'Basics', 'The original million-element bound is reduced to 200.', 'xprime_func.py', `def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    d = 3
    while d * d <= n:
        if n % d == 0:
            return False
        d += 2
    return True

limit = 200
count = 0
for n in range(2, limit + 1):
    if is_prime(n):
        count += 1
print("primes through", limit, count)
`),
  numpy: example('NumPy array', 'NumPy', 'An elementwise operation followed by a reduction.', null,
    'import numpy as np\n\nx = np.array([1.0, 2.0, 3.0])\ny = x * x\nprint(np.sum(y))\n'),
  reshape: example('C-order and Fortran-order reshape', 'NumPy', 'See how array order affects the rows of a matrix.', 'xrosetta.py', `import numpy as np

a = np.reshape([1, 2, 3, 4, 5, 6], (2, 3))
b = np.reshape([1, 2, 3, 4, 5, 6], (2, 3), order="F")
print("C order")
for i in range(2):
    print(a[i, 0], a[i, 1], a[i, 2])
print("Fortran order")
for i in range(2):
    print(b[i, 0], b[i, 1], b[i, 2])
`),
  masks: example('Boolean selection and assignment', 'NumPy', 'Select bounded values and update a masked integer array.', 'xrosetta.py', `import numpy as np

a = np.arange(1, 11)
mask = (a > 2) & (a < 6)
print("selected sum", np.sum(a[mask]))
print("selected count", np.count_nonzero(mask))
b = np.zeros(10, dtype=int)
b[a > 2] = 1
b[a > 5] = a[a > 5] - 3
for value in b:
    print(value)
`),
  matmul: example('Elementwise versus matrix multiplication', 'NumPy', 'Compare * with @ for two small integer matrices.', 'xrosetta.py', `import numpy as np

a = np.array([[1, 2], [3, 4]])
b = np.array([[2, 3], [4, 5]])
elementwise = a * b
product = a @ b
print("elementwise")
for i in range(2):
    print(elementwise[i, 0], elementwise[i, 1])
print("matrix product")
for i in range(2):
    print(product[i, 0], product[i, 1])
`),
  math: example('Elementwise mathematical functions', 'NumPy', 'Trigonometry and elementary real functions on vectors.', 'xnp_math_funcs.py', `import numpy as np

angles = np.array([0.0, np.pi / 6, np.pi / 4])
sines = np.sin(angles)
cosines = np.cos(angles)
for i in range(3):
    print("%.6f %.6f" % (sines[i], cosines[i]))
x = np.array([1.0, 2.0, 4.0])
print("sum of square roots", np.sum(np.sqrt(x)))
print("sum of logarithms", np.sum(np.log(x)))
`),
  norms: example('Vector and row norms', 'NumPy', 'Real vector norm and matrix norms along an axis.', 'xnorm.py', `import numpy as np

vector = np.array([3.0, 4.0])
matrix = np.array([[3.0, 4.0], [5.0, 12.0]])
print("vector norm", np.linalg.norm(vector))
row_norms = np.linalg.norm(matrix, axis=1)
for value in row_norms:
    print("row norm", value)
`),
  complex: example('Real and imaginary parts', 'NumPy', 'Complex arrays retain both components.', 'xreal_imag.py', `import numpy as np

z = np.array([1.0 + 2.0j, 3.0 - 4.0j, -2.0 + 0.5j])
real_part = np.real(z)
imag_part = np.imag(z)
for i in range(3):
    print(real_part[i], imag_part[i])
`),
  statistics: example('Python statistics module', 'Statistics', 'Center and dispersion for a small fixed data set.', 'xstats.py', `import statistics as stats

x = [12, 15, 15, 18, 20, 22, 25, 25, 25, 30]
print("mean", stats.mean(x))
print("median", stats.median(x))
print("mode", stats.mode(x))
print("population variance", stats.pvariance(x))
print("sample variance", stats.variance(x))
print("sample standard deviation", stats.stdev(x))
`),
  numpy_stats: example('NumPy moments, covariance and correlation', 'Statistics', 'Fixed inputs replace random draws so Compare is meaningful.', 'xnpstats.py', `import numpy as np

x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
y = np.array([1.0, 3.0, 2.0, 5.0, 4.0])
print("mean", np.mean(x))
print("standard deviation", np.std(x))
covariance = np.cov(x, y)
correlation = np.corrcoef(x, y)
print("covariance", covariance[0, 1])
print("correlation", correlation[0, 1])
`),
  interpolate: example('Linear interpolation', 'Numerical methods', 'Interpolate between samples of a quadratic.', 'xnp_math_funcs.py', `import numpy as np

x = np.array([0.5, 1.5, 2.5])
xp = np.array([0.0, 1.0, 2.0, 3.0])
fp = np.array([0.0, 1.0, 4.0, 9.0])
y = np.interp(x, xp, fp)
for i in range(3):
    print(x[i], y[i])
`),
  convolution: example('Discrete convolution', 'Numerical methods', 'A short full convolution with a three-element kernel.', 'xnp_math_funcs.py', `import numpy as np

x = np.array([1.0, 2.0, 3.0])
kernel = np.array([0.0, 1.0, 0.5])
y = np.convolve(x, kernel)
for value in y:
    print(value)
`),
  laplace: example('Two-dimensional stencil', 'Numerical methods', 'One interior Laplace update; boundaries stay unchanged.', 'xrosetta.py', `import numpy as np

u = np.zeros((5, 5))
u[0, :] = 1.0
dx2 = 0.25
dy2 = 0.50
u[1:-1, 1:-1] = (
    (u[2:, 1:-1] + u[:-2, 1:-1]) * dy2
    + (u[1:-1, 2:] + u[1:-1, :-2]) * dx2
) / (2.0 * (dx2 + dy2))
for i in range(5):
    print(u[i, 0], u[i, 1], u[i, 2], u[i, 3], u[i, 4])
`),
  solve: example('Solve a linear system', 'Linear algebra', 'Simplified illustration of the solver used by the Rosetta fitting example.', 'xrosetta.py', `import numpy as np

a = np.array([[3.0, 1.0], [1.0, 2.0]])
b = np.array([9.0, 8.0])
x = np.linalg.solve(a, b)
print("solution", x[0], x[1])
print("residual norm", np.linalg.norm(a @ x - b))
`),
  least_squares: example('Fit a straight line', 'Linear algebra', 'Small fixed-data adaptation of the least-squares design matrix in the VAR example.', 'xvar_order_2.py', `import numpy as np

x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
y = np.array([1.1, 2.9, 5.2, 6.8, 9.3])
design = np.column_stack((np.ones(5), x))
coefficients, residuals, rank, singular_values = np.linalg.lstsq(design, y, rcond=None)
print("intercept", coefficients[0])
print("slope", coefficients[1])
print("rank", rank)
print("squared residual", residuals[0])
`),
  normal: example('Normal sampling (random)', 'Simulation', 'A small normal sample summarized by its moments.', 'xrandom_normal.py', `import numpy as np

n = 1000
x = np.random.normal(size=n)
print(n, np.mean(x), np.std(x), np.min(x), np.max(x))
`, true),
  dice: example('Two-dice simulation (random)', 'Simulation', 'Estimate the probability of a sum of seven in 1000 rolls.', 'xrandom.py', `import random

random.seed(12345)
nrolls = 1000
count_seven = 0
for i in range(nrolls):
    die1 = random.randint(1, 6)
    die2 = random.randint(1, 6)
    if die1 + die2 == 7:
        count_seven += 1
print("rolls", nrolls)
print("sevens", count_seven)
print("estimated probability", count_seven / nrolls)
`, true),
};

const escapeHTML = text => text.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
  .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
export function populateExamples(select) {
  const groups = new Map();
  for (const [id, item] of Object.entries(pythonExamples)) {
    if (!groups.has(item.category)) groups.set(item.category, []);
    groups.get(item.category).push(`<option value="${escapeHTML(id)}">${escapeHTML(item.title)}</option>`);
  }
  select.innerHTML = [...groups].map(([category, options]) =>
    `<optgroup label="${escapeHTML(category)}">${options.join('')}</optgroup>`).join('');
  select.value = 'sum';
}
export function describeExample(get) {
  const item = pythonExamples[get('example').value];
  if (!item) return;
  get('example-description').textContent = item.description + (item.random ?
    ' Python and Fortran draws differ, even with equal seeds; Compare can report DIFF.' : '');
  const link = get('example-source');
  link.hidden = !item.upstream;
  link.href = item.upstream ? `https://github.com/beliavsky/python-to-fortran/blob/main/examples/${item.upstream}` : '';
  link.textContent = item.upstream ? `Adapted from ${item.upstream}` : '';
}
