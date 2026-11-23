// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "Logging/LogMacros.h"
#include "OpenWorldCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;
class UStaticMeshComponent;
class UStaticMesh;
class UInputAction;
class UInputMappingContext;
class UAnimSequence;
class UOpenWorldAnimInstance;
class UOpenWorldPhysicalMaterial;
class AOpenWorldProp;
struct FInputActionValue;
struct FHitResult;

DECLARE_LOG_CATEGORY_EXTERN(LogTemplateCharacter, Log, All);

/** A set of equipment the character can switch to, with its attack */
USTRUCT(BlueprintType)
struct FOpenWorldLoadout
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	FText DisplayName;

	/** Weapon in the right hand */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	TObjectPtr<UStaticMesh> MainHandMesh;

	/** Shield (or nothing) in the left hand */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	TObjectPtr<UStaticMesh> OffHandMesh;

	/** Combat stance: the arms hold this pose while standing, walking and running; the knees bend while standing */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	TObjectPtr<UAnimSequence> StanceAnimation;

	/** Scabbard at the hip (stays there, empty, while the weapon is drawn). Null = none. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	TObjectPtr<UStaticMesh> ScabbardMesh;

	/** Where the right-hand weapon sits when put away: a bone and the weapon's grip frame in that bone's space */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	FName MainHandSheathBone;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	FTransform MainHandSheathTransform;

	/** The same for the shield */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	FName OffHandSheathBone;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	FTransform OffHandSheathTransform;

	/**
	 *  With the weapons put away, how far the arms are pulled toward SheathedArmPose (0 = not at all).
	 *  A big shield on the back leaves less room for the elbows than the plain running animation uses.
	 *  Must match SHEATHED_ARM_DAMPING in Tools/owlib.py, which the collision audit uses.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed", meta=(ClampMin="0", ClampMax="1"))
	float SheathedArmDamping = 0.f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout|Sheathed")
	TObjectPtr<UAnimSequence> SheathedArmPose;

	/** Attack animation, played over the upper body (and the whole body while standing). Starts and ends in the stance. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	TObjectPtr<UAnimSequence> AttackAnimation;

	/** Part of the attack animation in which the blade can strike something: from the top of the wind-up... */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0", Units="s"))
	float HitWindowStart = 0.27f;

	/** ...to the end of the follow-through */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0", Units="s"))
	float HitWindowEnd = 0.52f;

	/** From this time on a queued click chains straight into the next attack */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0", Units="s"))
	float ComboTime = 0.66f;

	/** The blade along the grip socket's Z axis: where it starts above the hand... */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(Units="cm"))
	float BladeStart = 8.4f;

	/** ...and where its tip is */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(Units="cm"))
	float BladeEnd = 88.4f;

	/** Half thickness of the blade, used when sweeping it through the world */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0.1", Units="cm"))
	float BladeRadius = 1.5f;

	/** Damage of a full-speed hit on a material of the same hardness */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0"))
	float Damage = 1.f;

	/** Mass of the weapon; with the blade's speed it gives the push a hit delivers */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout", meta=(ClampMin="0", Units="kg"))
	float WeaponMass = 1.3f;

	/** What the blade is made of (hardness decides whether it bites into a surface or rings off it) */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Loadout")
	TObjectPtr<UOpenWorldPhysicalMaterial> WeaponSubstance;
};

/** The last time a weapon met a surface */
struct FOpenWorldContact
{
	bool bValid = false;
	bool bBites = false;
	float Time = 0.f;
	float Damage = 0.f;
	FVector ImpactPoint = FVector::ZeroVector;
	TWeakObjectPtr<UPrimitiveComponent> Target;
};

/**
 *  A simple player-controllable third person character
 *  Implements a controllable orbiting camera
 */
UCLASS(abstract)
class AOpenWorldCharacter : public ACharacter
{
	GENERATED_BODY()

	/** Camera boom positioning the camera behind the character */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	USpringArmComponent* CameraBoom;

	/** Weapon held in the right hand */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UStaticMeshComponent* Weapon;

	/** Shield held in the left hand */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UStaticMeshComponent* OffHandWeapon;

	/** Scabbard at the hip */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UStaticMeshComponent* Scabbard;

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

	/** Switch to the next loadout (click of the mouse wheel). Created at runtime if left empty. */
	UPROPERTY(EditAnywhere, Category="Input|Combat")
	TObjectPtr<UInputAction> SwitchLoadoutAction;

	/** Socket on the character mesh the right-hand weapon is attached to */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon")
	FName WeaponSocketName = TEXT("HandGrip_R");

	/** Socket on the character mesh the left-hand shield is attached to */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon")
	FName OffHandSocketName = TEXT("HandGrip_L");

	/** Equipment sets; the mouse wheel click cycles through them */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon")
	TArray<FOpenWorldLoadout> Loadouts;

	/** Loadout equipped when the game starts */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon", meta=(ClampMin="0"))
	int32 StartingLoadoutIndex = 0;

	/** A left button press shorter than this counts as an attack click instead of a camera drag */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="s"))
	float AttackClickMaxDuration = 0.25f;

	/** Mouse movement allowed during a click before it is treated as a camera drag */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0"))
	float AttackClickMaxMouseTravel = 10.f;

	/** Turn the character to the camera direction when an attack starts while standing */
	UPROPERTY(EditAnywhere, Category="Combat|Attack")
	bool bFaceCameraOnAttack = true;

	/** The weapons are put away this long after the last press of the attack button */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon", meta=(ClampMin="0", Units="s"))
	float CombatTimeout = 15.f;

	/** How long the arms take to move between carrying nothing and the combat stance */
	UPROPERTY(EditAnywhere, Category="Combat|Weapon", meta=(ClampMin="0", Units="s"))
	float StanceBlendTime = 0.3f;

	/** A click this long before the combo window still continues the combo */
	UPROPERTY(EditAnywhere, Category="Combat|Attack", meta=(ClampMin="0", Units="s"))
	float ComboInputCacheTime = 0.45f;

	/** Points along the blade that are swept through the world every frame of the cut */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="2", ClampMax="16"))
	int32 BladeSamples = 7;

	/** Bone the attack's upper body hangs from; bones above it are predicted from the attack animation */
	UPROPERTY(EditAnywhere, Category="Combat|Contact")
	FName BladeChainRootParent = TEXT("pelvis");

	/** How much of the body's weight is behind the blade, as a multiple of the weapon's mass */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0"))
	float StrikeMassScale = 3.f;

	/** The blade bites into a surface when it is at least this many times harder than it; otherwise it rings off */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0"))
	float BiteHardnessRatio = 1.2f;

	/** Hardness assumed for surfaces and blades without an OpenWorld physical material */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0.1"))
	float DefaultHardness = 5.f;

	/** Blade speed at which a hit deals the loadout's full damage */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="1", Units="cm/s"))
	float ReferenceBladeSpeed = 1200.f;

	/** How long the blade stays stuck after biting into a softer material... */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0", Units="s"))
	float BiteHoldTime = 0.12f;

	/** ...and how fast it is then drawn back along the path it came by (1 = the speed of the swing) */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0.1"))
	float BiteRewindRate = 1.2f;

	/** The same for a blade that rings off a material as hard as itself */
	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0", Units="s"))
	float BounceHoldTime = 0.04f;

	UPROPERTY(EditAnywhere, Category="Combat|Contact", meta=(ClampMin="0.1"))
	float BounceRewindRate = 2.0f;

	/** Print what met what, with hardness and damage, on screen */
	UPROPERTY(EditAnywhere, Category="Combat|Contact")
	bool bShowContactReports = true;

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

	/** Starts an attack, or queues the next one if already attacking */
	void Attack();
	void StartAttack();

	/** Advances the running attack: blade contact, combo chaining, end */
	void UpdateAttack(float DeltaSeconds);

	/** World positions of points along the blade at a time of the attack animation, before that pose is on screen */
	bool PredictBladePoints(const FOpenWorldLoadout& Loadout, float Time, const FTransform& MeshToWorld, TArray<FVector>& OutPoints) const;

	/** Sweeps the blade from where it is to where the animation is about to put it; stops the swing at the first surface */
	void UpdateBladeContact(float DeltaSeconds);

	/** The blade met a surface at ContactTime of the attack: stop there, then let the materials and physics decide */
	void ResolveContact(const FOpenWorldLoadout& Loadout, const FHitResult& Hit, const FVector& BladeVelocity, float ContactTime);

	UOpenWorldAnimInstance* GetOverlayAnimInstance() const;

private:

	float TargetZoomDistance = 400.f;
	float DefaultRotationRateYaw = 500.f;
	float DefaultWalkSpeed = 500.f;
	bool bCameraRotating = false;
	bool bCameraOrbiting = false;

	/** Left button click detection */
	float OrbitPressTime = 0.f;
	float OrbitMouseTravel = 0.f;

	/** Attack state */
	int32 CurrentLoadoutIndex = INDEX_NONE;

	/** Weapons in the hands (combat) or on the body (not in combat) */
	bool bWeaponsDrawn = false;
	float LastCombatInputTime = -1000.f;

	/** Attaches weapons, shield and scabbard to hands or body and sets the arms' stance for the current state */
	void ApplyWeaponState();
	bool bIsAttacking = false;
	float CachedAttackInputTime = -1000.f;

	/** Blade contact: points along the blade in the pose that is on screen, and whether this swing already hit */
	TArray<FVector> BladePoints;
	bool bBladeTracked = false;
	bool bContactDone = false;
	FOpenWorldContact LastContact;

#if !UE_BUILD_SHIPPING
	/** Scripted run started with -OWSelfTest on the command line; logs what the attacks do */
	void TickSelfTest(float DeltaSeconds);
	bool bSelfTest = false;
	float SelfTestTime = 0.f;
	float SelfTestNextLog = 0.f;
	int32 SelfTestStep = 0;
	TWeakObjectPtr<AOpenWorldProp> SelfTestTarget;
	FVector SelfTestTargetStart = FVector::ZeroVector;
	float SelfTestMaxDepth = 0.f;
	float SelfTestMaxPredictionError = 0.f;
	TArray<FVector> SelfTestPredicted;
	TArray<FVector> SelfTestPredictedEarlier;
#endif

public:

	/** True while an attack animation is playing */
	UFUNCTION(BlueprintPure, Category="Combat")
	bool IsAttacking() const { return bIsAttacking; }

	/** Equips the loadout with this index */
	UFUNCTION(BlueprintCallable, Category="Combat")
	void EquipLoadout(int32 Index);

	/** Takes the weapons into the hands and goes into the combat stance */
	UFUNCTION(BlueprintCallable, Category="Combat")
	void DrawWeapons();

	/** Puts the weapons away: sword into the scabbard, shield or two-handed sword on the back */
	UFUNCTION(BlueprintCallable, Category="Combat")
	void SheatheWeapons();

	UFUNCTION(BlueprintPure, Category="Combat")
	bool AreWeaponsDrawn() const { return bWeaponsDrawn; }

	/** Equips the next loadout in the list */
	UFUNCTION(BlueprintCallable, Category="Combat")
	void EquipNextLoadout();

	UFUNCTION(BlueprintPure, Category="Combat")
	int32 GetCurrentLoadoutIndex() const { return CurrentLoadoutIndex; }

	/** Returns the right-hand weapon component */
	FORCEINLINE UStaticMeshComponent* GetWeapon() const { return Weapon; }

	/** Returns the left-hand shield component */
	FORCEINLINE UStaticMeshComponent* GetOffHandWeapon() const { return OffHandWeapon; }

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

