// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "Logging/LogMacros.h"
#include "Animation/AnimInstance.h"
#include "CombatAttacker.h"
#include "OpenWorldCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class UInputAction;
class UInputMappingContext;
class UAnimMontage;
struct FInputActionValue;

DECLARE_LOG_CATEGORY_EXTERN(LogTemplateCharacter, Log, All);

/**
 *  A simple player-controllable third person character
 *  Implements a controllable orbiting camera
 */
UCLASS(abstract)
class AOpenWorldCharacter : public ACharacter, public ICombatAttacker
{
	GENERATED_BODY()

	/** Camera boom positioning the camera behind the character */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	USpringArmComponent* CameraBoom;

	/** Weapon held in the right hand */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UStaticMeshComponent* Weapon;

	/** Follow camera */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UCameraComponent* FollowCamera;
	
protected:

	/** Jump Input Action */
	UPROPERTY(EditAnywhere, Category="Input")
	UInputAction* JumpAction;

	/** Move Input Action */
	UPROPERTY(EditAnywhere, Category="Input")
	UInputAction* MoveAction;

	/** Look Input Action */
	UPROPERTY(EditAnywhere, Category="Input")
	UInputAction* LookAction;

	/** Mouse Look Input Action (only applied while a camera mouse button is held) */
	UPROPERTY(EditAnywhere, Category="Input")
	UInputAction* MouseLookAction;

	/** Camera zoom (mouse wheel, Axis1D). Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Camera")
	TObjectPtr<UInputAction> CameraZoomAction;

	/** Hold to rotate the camera and turn the character with it (right mouse button). Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Camera")
	TObjectPtr<UInputAction> CameraRotateAction;

	/** Hold to orbit the camera around the character without turning it (left mouse button). Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Camera")
	TObjectPtr<UInputAction> CameraOrbitAction;

	/** Mapping context for the camera actions. Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Camera")
	TObjectPtr<UInputMappingContext> CameraMappingContext;

	/** Priority of the camera mapping context (higher wins over the default contexts) */
	UPROPERTY(EditAnywhere, Category="Input|Camera")
	int32 CameraMappingPriority = 1;

	/** Closest camera distance from the character */
	UPROPERTY(EditAnywhere, Category="Camera|Zoom", meta=(ClampMin="0", Units="cm"))
	float MinZoomDistance = 150.f;

	/** Farthest camera distance from the character */
	UPROPERTY(EditAnywhere, Category="Camera|Zoom", meta=(ClampMin="0", Units="cm"))
	float MaxZoomDistance = 1500.f;

	/** Distance change per mouse wheel notch */
	UPROPERTY(EditAnywhere, Category="Camera|Zoom", meta=(ClampMin="0", Units="cm"))
	float ZoomStep = 100.f;

	/** How quickly the camera reaches the target zoom distance (0 = instant) */
	UPROPERTY(EditAnywhere, Category="Camera|Zoom", meta=(ClampMin="0"))
	float ZoomInterpSpeed = 10.f;

	/** Holding both camera buttons walks the character forward */
	UPROPERTY(EditAnywhere, Category="Camera|Rotation")
	bool bBothButtonsMoveForward = true;

	/** How fast the character turns to face the camera direction while rotating (degrees per second) */
	UPROPERTY(EditAnywhere, Category="Camera|Rotation", meta=(ClampMin="0"))
	float FaceCameraRotationRate = 720.f;

	/** Hold to sprint (Left Shift). Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Movement")
	TObjectPtr<UInputAction> SprintAction;

	/** Movement speed while sprinting */
	UPROPERTY(EditAnywhere, Category="Movement|Sprint", meta=(ClampMin="0", Units="cm/s"))
	float SprintSpeed = 850.f;

	/** Socket on the character mesh the weapon is attached to */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon")
	FName WeaponSocketName = TEXT("HandGrip_R");

	/** Attack animation montage; each montage section is one hit of the combo */
	UPROPERTY(EditAnywhere, Category="Combat|Attack")
	TObjectPtr<UAnimMontage> AttackMontage;

	/** A left button press shorter than this counts as an attack click instead of a camera drag */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="s"))
	float AttackClickMaxDuration = 0.25f;

	/** Mouse movement allowed during a click before it is treated as a camera drag */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0"))
	float AttackClickMaxMouseTravel = 10.f;

	/** Turn the character to the camera direction when an attack starts */
	UPROPERTY(EditAnywhere, Category="Combat|Attack")
	bool bFaceCameraOnAttack = true;

	/** A click this long before the combo window still continues the combo */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="s"))
	float ComboInputCacheTime = 0.45f;

	/** Reach of the attack hit check */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="cm"))
	float MeleeTraceDistance = 110.f;

	/** Radius of the attack hit check */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="cm"))
	float MeleeTraceRadius = 45.f;

	/** Damage dealt per hit */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0"))
	float MeleeDamage = 1.f;

	/** Knockback applied to hit targets */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0"))
	float MeleeKnockbackImpulse = 250.f;

public:

	/** Constructor */
	AOpenWorldCharacter();

	virtual void Tick(float DeltaSeconds) override;

protected:

	virtual void BeginPlay() override;

	/** Initialize input action bindings */
	virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;

	/** Creates the camera input actions and mapping context if they were not assigned, and registers the context */
	void SetupCameraInput();

	void MouseLook(const FInputActionValue& Value);
	void CameraZoom(const FInputActionValue& Value);
	void CameraRotateStarted();
	void CameraRotateCompleted();
	void CameraOrbitStarted();
	void CameraOrbitCompleted();

	/** Switches between "face movement direction" and "face camera direction" */
	void UpdateRotationMode();

	/** True while a camera mouse button is held */
	bool IsCameraControlActive() const { return bCameraRotating || bCameraOrbiting; }

	void SprintStarted();
	void SprintCompleted();

	/** Starts the attack combo, or queues the next hit if already attacking */
	void Attack();
	void PlayAttackMontage();
	void AttackMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	// ICombatAttacker (called from the attack montage's AnimNotifies)
	virtual void DoAttackTrace(FName DamageSourceBone) override;
	virtual void CheckCombo() override;
	virtual void CheckChargedAttack() override {}

private:

	float TargetZoomDistance = 400.f;
	float DefaultRotationRateYaw = 500.f;
	float DefaultWalkSpeed = 500.f;
	bool bCameraRotating = false;
	bool bCameraOrbiting = false;

	/** Left button click detection */
	float OrbitPressTime = 0.f;
	float OrbitMouseTravel = 0.f;

	/** Combo state */
	bool bIsAttacking = false;
	int32 ComboCount = 0;
	float CachedAttackInputTime = -1000.f;
	TArray<FName> ComboSectionNames;
	FOnMontageEnded OnAttackMontageEnded;

public:

	/** True while the attack montage is playing */
	UFUNCTION(BlueprintPure, Category="Combat")
	bool IsAttacking() const { return bIsAttacking; }

	/** Returns the weapon component */
	FORCEINLINE UStaticMeshComponent* GetWeapon() const { return Weapon; }

public:

	/** Sets the camera distance (clamped to the zoom limits) */
	UFUNCTION(BlueprintCallable, Category="Camera")
	void SetZoomDistance(float Distance, bool bInstant = false);

protected:

	/** Called for movement input */
	void Move(const FInputActionValue& Value);

	/** Called for looking input */
	void Look(const FInputActionValue& Value);

public:

	/** Handles move inputs from either controls or UI interfaces */
	UFUNCTION(BlueprintCallable, Category="Input")
	virtual void DoMove(float Right, float Forward);

	/** Handles look inputs from either controls or UI interfaces */
	UFUNCTION(BlueprintCallable, Category="Input")
	virtual void DoLook(float Yaw, float Pitch);

	/** Handles jump pressed inputs from either controls or UI interfaces */
	UFUNCTION(BlueprintCallable, Category="Input")
	virtual void DoJumpStart();

	/** Handles jump pressed inputs from either controls or UI interfaces */
	UFUNCTION(BlueprintCallable, Category="Input")
	virtual void DoJumpEnd();

public:

	/** Returns CameraBoom subobject **/
	FORCEINLINE class USpringArmComponent* GetCameraBoom() const { return CameraBoom; }

	/** Returns FollowCamera subobject **/
	FORCEINLINE class UCameraComponent* GetFollowCamera() const { return FollowCamera; }
};

