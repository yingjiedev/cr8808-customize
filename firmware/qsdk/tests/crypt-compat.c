/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Public fixed fixture; no device password is used in CI. */
#include <crypt.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *actual;
    if (argc != 3)
        return 2;
    actual = crypt("cr8808-qsdk-ci-password", argv[1]);
    if (!actual || strcmp(actual, argv[2])) {
        fputs("Image libc password crypt compatibility failed\n", stderr);
        return 1;
    }
    puts("Image libc password crypt compatibility passed");
    return 0;
}
