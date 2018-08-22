/*
 * Copyright (c) 2017 Intel Corp
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <zephyr.h>
#include <misc/printk.h>
#include <drivers/rand32.h>

int run_some_test(void)
{
	uint32_t r;
	r = sys_rand32_get();
	return r & 0x1;
}

void main(void)
{
	if (run_some_test())
		printk("PASS\n");
	else
		printk("FAIL\n");
}
