/*
 * Copyright (c) 2017 Intel Corporation
 *
 * SPDX-License-Identifier: Apache-2.0
 */

void setup(void)
{
	Serial.begin(115200);
}

void loop(void)
{
	while (!0) {
		Serial.println("Hello World!\n");
		delay(1000);
	}
}
