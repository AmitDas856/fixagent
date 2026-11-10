// Test runner. Run from the project root with: hhvm tests/run_tests.hack

function expect_eq(int $actual, int $expected, string $name): int {
  if ($actual === $expected) {
    echo "ok   ".$name."\n";
    return 0;
  }
  echo "FAIL ".$name." (expected ".$expected.", got ".$actual.")\n";
  return 1;
}

<<__EntryPoint>>
function run_tests(): noreturn {
  require_once(__DIR__.'/../src/cart.hack');

  $failures = 0;
  $failures += expect_eq(cart_total(vec[]), 0, 'empty cart totals zero');
  $failures += expect_eq(
    cart_total(vec[tuple(250, 1)]),
    250,
    'single item with quantity one',
  );
  $failures += expect_eq(
    cart_total(vec[tuple(250, 2), tuple(100, 3)]),
    800,
    'total multiplies price by quantity',
  );
  $failures += expect_eq(
    cart_total(vec[tuple(999, 0)]),
    0,
    'quantity zero adds nothing',
  );
  $failures += expect_eq(apply_discount(1000, 10), 900, 'ten percent off');
  $failures += expect_eq(apply_discount(999, 0), 999, 'zero percent off');
  $failures += expect_eq(
    item_count(vec[tuple(250, 2), tuple(100, 3)]),
    5,
    'item count adds quantities',
  );

  if ($failures > 0) {
    echo $failures." test(s) failed\n";
    exit(1);
  }
  echo "all tests passed\n";
  exit(0);
}
