/*
 * Copyright (c) 2017 Intel Corp
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr.h>
#include <misc/printk.h>
#include <drivers/rand32.h>
#include <tc_util.h>

int run_some_test(void)
{
	uint32_t r;
	r = sys_rand32_get();
	return r & 0x1;
}

void main(void)
{
	int r;
	TC_START("random test");
	if (run_some_test())
		r = TC_PASS;
	else
		r = TC_FAIL;
	TC_END_RESULT(r);
	TC_END_REPORT(r);
}
