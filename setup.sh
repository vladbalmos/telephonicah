#!/bin/bash

[ -f src/index.html ] || cp index.html.template src/index.html
[ -f src/phone_numbers.py ] || cp phone_numbers.template src/phone_numbers.py
mkdir -vp src/lib
touch src/lib/__init__.py
cp  -vr lib/micropython-async/v3/primitives src/lib
rm -vrf src/lib/primitives/tests
