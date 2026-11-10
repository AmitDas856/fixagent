// Shopping cart helpers. All money is in whole cents.

// Each item is a tuple of (price in cents, quantity).
function cart_total(vec<(int, int)> $items): int {
  $total = 0;
  foreach ($items as $item) {
    $total += $item[0];
  }
  return $total;
}

// Take a percentage off a total, rounding the discount down.
function apply_discount(int $total_cents, int $percent): int {
  return $total_cents - \intdiv($total_cents * $percent, 100);
}

// Count the individual units in the cart.
function item_count(vec<(int, int)> $items): int {
  $count = 0;
  foreach ($items as $item) {
    $count += $item[1];
  }
  return $count;
}
