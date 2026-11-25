-- One database per pytest-xdist worker, as the CI integration stage creates them
-- (.woodpecker/test-integration.yml). tests/conftest.py appends `_gwN` to the
-- database name for each worker.
CREATE DATABASE test_batchivo_gw0;
CREATE DATABASE test_batchivo_gw1;
CREATE DATABASE test_batchivo_gw2;
CREATE DATABASE test_batchivo_gw3;
