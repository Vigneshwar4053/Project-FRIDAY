#ifndef FRIDAY_SYNC_H
#define FRIDAY_SYNC_H

/* Process-local, single-owner binary gate. No scheduling/model logic.
 * Handles must be valid and live. Destroy only after all users have stopped.
 * acquire/release/destroy return 0 on success or a POSIX error number.
 * create returns NULL on failure and sets errno. Destroy(NULL) returns EINVAL.
 * Failed destroy leaves the handle valid; successful destroy invalidates it.
 */
typedef struct FridaySemaphore FridaySemaphore;

FridaySemaphore *friday_semaphore_create(void);
int friday_semaphore_acquire(FridaySemaphore *sem);
int friday_semaphore_release(FridaySemaphore *sem);
int friday_semaphore_destroy(FridaySemaphore *sem);

#endif
