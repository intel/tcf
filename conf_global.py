#! /usr/bin/python

import tcfl.tc_clear_bbt
tcfl.tc.tc_c.driver_add(tcfl.tc_clear_bbt.tc_clear_bbt_c)

import tcfl.tc_jtreg
tcfl.tc.tc_c.driver_add(tcfl.tc_jtreg._driver)
