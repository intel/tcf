/*
 * Copyright (c) 2017 Intel Corp
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr.h>
#include <misc/printk.h>
#include <drivers/rand32.h>
#include <ztest.h>

void run_some_test1(void)
{
	uint32_t r = sys_rand32_get();
	zassert_true(r & 0x1, "random1");
}

void run_some_test2(void)
{
	uint32_t r = sys_rand32_get();
	zassert_true(r & 0x1, "random2");
}

void test_main(void)			/* note test_main() */
{
	ztest_test_suite(		/* declare the test suite */
		test_18,
		ztest_unit_test(run_some_test1),
		ztest_unit_test(run_some_test2));
	ztest_run_test_suite(test_18);	/* run it */
}
