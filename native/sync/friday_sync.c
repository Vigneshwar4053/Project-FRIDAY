#define _POSIX_C_SOURCE 200809L
#include "friday_sync.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>

struct FridaySemaphore {
    pthread_mutex_t mutex;
};

FridaySemaphore *friday_semaphore_create(void)
{
    FridaySemaphore *sem = malloc(sizeof(*sem));
    pthread_mutexattr_t attr;
    int rc;
    if (sem == NULL) {
        errno = ENOMEM;
        return NULL;
    }
    rc = pthread_mutexattr_init(&attr);
    if (rc != 0) {
        free(sem);
        errno = rc;
        return NULL;
    }
    rc = pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_ERRORCHECK);
    if (rc == 0) {
        rc = pthread_mutex_init(&sem->mutex, &attr);
    }
    (void)pthread_mutexattr_destroy(&attr);
    if (rc != 0) {
        free(sem);
        errno = rc;
        return NULL;
    }
    return sem;
}

int friday_semaphore_acquire(FridaySemaphore *sem)
{
    return sem == NULL ? EINVAL : pthread_mutex_lock(&sem->mutex);
}

int friday_semaphore_release(FridaySemaphore *sem)
{
    return sem == NULL ? EINVAL : pthread_mutex_unlock(&sem->mutex);
}

int friday_semaphore_destroy(FridaySemaphore *sem)
{
    int rc;
    if (sem == NULL) {
        return EINVAL;
    }
    rc = pthread_mutex_destroy(&sem->mutex);
    if (rc == 0) {
        free(sem);
    }
    return rc;
}
