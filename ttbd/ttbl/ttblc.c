/*
 * Copyright (c) 2017 Intel Corporation
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <Python.h>
#include <signal.h>
#include <wait.h>

static PyObject* waitid_poll(PyObject* self)
{
	int r;
	siginfo_t si = { .si_pid = 0 };
	r = waitid(P_ALL, 0, &si, WNOHANG | WEXITED | WNOWAIT);
	if (r != 0)
		return Py_BuildValue("i", -1);
	if (si.si_pid == 0)
		return Py_BuildValue("i", 0);
	return Py_BuildValue("i", si.si_pid);
}

static char waitid_poll_docs[] =
    "waitid_poll(): Return pid of process that is available to wait on\n";

static PyMethodDef ttblc_funcs[] = {
	{
		"waitid_poll", (PyCFunction) waitid_poll,
		METH_NOARGS, waitid_poll_docs
	},
	{ NULL }
};

void initttblc(void)
{
#if PY_MAJOR_VERSION >= 3
    static struct PyModuleDef moduledef = {
	    PyModuleDef_HEAD_INIT,
	    "ttblc",             /* m_name */
	    "TTBL C functions!", /* m_doc */
	    -1,                  /* m_size */
	    ttblc_funcs,         /* m_methods */
	    NULL,                /* m_reload */
	    NULL,                /* m_traverse */
	    NULL,                /* m_clear */
	    NULL,                /* m_free */
    };
#endif

#if PY_MAJOR_VERSION >= 3
    PyModule_Create(&moduledef);
#else
    Py_InitModule3("ttblc", ttblc_funcs, "TTBL C functions!");
#endif
}
