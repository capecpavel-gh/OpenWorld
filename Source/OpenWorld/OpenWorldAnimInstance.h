// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "OpenWorldAnimInstance.generated.h"

class UAnimSequence;

/**
 *  Evaluates the Anim Blueprint graph and then layers on top of it:
 *  1. the stance (how the equipped weapons are carried) on both arms, and on the rest of the body
 *     while the character stands (bent knees of the combat stance),
 *  2. an "overlay" animation such as an attack: fully on the upper body, and on the lower body
 *     only as far as LowerBodyWeight says.
 */
USTRUCT()
struct FOpenWorldAnimInstanceProxy : public FAnimInstanceProxy
{
	GENERATED_BODY()

	FOpenWorldAnimInstanceProxy() = default;
	explicit FOpenWorldAnimInstanceProxy(UAnimInstance* Instance) : FAnimInstanceProxy(Instance) {}

protected:

	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate_WithRoot(FPoseContext& Output, FAnimNode_Base* InRootNode) override;

private:

	void ApplyStance(FPoseContext& Output);
	void ApplyOverlay(FPoseContext& Output);
	void UpdateBoneMasks(const FBoneContainer& Bones);

	// Copied from the anim instance on the game thread; the instance keeps the sequences alive.
	const UAnimSequence* Sequence = nullptr;
	const UAnimSequence* PreviousSequence = nullptr;
	float Time = 0.f;
	float PreviousTime = 0.f;
	float CrossfadeAlpha = 1.f;
	float Weight = 0.f;
	float LowerBodyWeight = 0.f;
	FName UpperBodyRootBone;

	const UAnimSequence* Stance = nullptr;
	const UAnimSequence* PreviousStance = nullptr;
	float StanceAlpha = 1.f;
	float StanceArmWeight = 1.f;
	float PreviousStanceArmWeight = 1.f;
	bool bStanceWholeBody = false;
	bool bPreviousStanceWholeBody = false;
	TArray<FName> StanceRootBones;

	/** Per compact-pose bone: 1 if the bone belongs to the upper body / to the arms that hold the stance */
	TArray<uint8> UpperBodyMask;
	TArray<uint8> StanceMask;
	FName MaskRootBone;
	TArray<FName> MaskStanceRootBones;
	uint16 MaskSerialNumber = 0;
};

/**
 *  Anim instance base class for the player character's Anim Blueprint.
 *  Lets C++ play an animation over the locomotion: the upper body always follows it,
 *  the legs follow it only while the character stands still, so attacking does not stop running.
 */
UCLASS()
class UOpenWorldAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:

	/**
	 *  Sets how the equipped weapons are carried: the arms take this pose in every locomotion state,
	 *  so a held weapon or shield never swings through the body. Null = arms follow the Anim Blueprint.
	 *  ArmWeight below 1 only pulls the arms part of the way toward the pose (calms their swing).
	 *  bWholeBodyWhenStanding: while the character stands, the rest of the body takes the pose too.
	 */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void SetStance(UAnimSequence* Sequence, float BlendTime = 0.25f, float ArmWeight = 1.f, bool bWholeBodyWhenStanding = false);

	/** Plays an animation on top of the Anim Blueprint's pose. Calling it while one is playing cross-fades into the new one. */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void PlayOverlay(UAnimSequence* Sequence, float BlendInTime = 0.1f, float BlendOutTime = 0.22f);

	/** Freezes the current overlay animation where it is and fades it out */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void StopOverlay(float BlendOutTime = 0.15f);

	/**
	 *  Lets the overlay animation play only up to AtTime, holds that pose for HoldSeconds and then fades it out.
	 */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void HoldOverlay(float AtTime, float HoldSeconds, float BlendOutTime);

	/**
	 *  Lets the overlay animation play only up to AtTime, holds that pose for HoldSeconds and then plays it
	 *  backwards to its start at RewindRate times normal speed.
	 *  Used when a weapon meets a surface: the swing stops exactly at the moment of contact and the weapon
	 *  goes back the way it came, which is the one path known to be free.
	 */
	UFUNCTION(BlueprintCallable, Category="Overlay")
	void HoldAndRewindOverlay(float AtTime, float HoldSeconds, float RewindRate);

	UFUNCTION(BlueprintPure, Category="Overlay")
	bool IsOverlayPlaying() const { return OverlaySequence != nullptr; }

	/** Current time in the overlay animation [s] */
	UFUNCTION(BlueprintPure, Category="Overlay")
	float GetOverlayTime() const { return OverlayTime; }

	/** How much the legs and hips follow the overlay animation right now (1 = standing, 0 = running) */
	UFUNCTION(BlueprintPure, Category="Overlay")
	float GetLowerBodyWeight() const { return LowerBodyWeight; }

	/** How strongly the overlay animation is applied right now (0..1) */
	UFUNCTION(BlueprintPure, Category="Overlay")
	float GetOverlayWeight() const { return OverlayWeight; }

	/** True once the overlay has been told to stop (it may still be holding or fading out) */
	UFUNCTION(BlueprintPure, Category="Overlay")
	bool IsOverlayStopping() const { return OverlayStopTime >= 0.f; }

protected:

	/** This bone and everything below it always follows the overlay animation */
	UPROPERTY(EditAnywhere, Category="Overlay")
	FName UpperBodyRootBone = TEXT("spine_01");

	/** These bones and everything below them hold the stance pose */
	UPROPERTY(EditAnywhere, Category="Overlay")
	TArray<FName> StanceRootBones = { TEXT("upperarm_l"), TEXT("upperarm_r") };

	/** Below this speed the legs and hips follow the overlay animation too */
	UPROPERTY(EditAnywhere, Category="Overlay", meta=(ClampMin="0", Units="cm/s"))
	float FullBodyMaxSpeed = 20.f;

	/** How quickly the legs switch between the overlay animation and locomotion */
	UPROPERTY(EditAnywhere, Category="Overlay", meta=(ClampMin="0"))
	float LowerBodyBlendSpeed = 8.f;

	virtual void NativeUpdateAnimation(float DeltaSeconds) override;
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;

private:

	friend struct FOpenWorldAnimInstanceProxy;

	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> OverlaySequence;

	/** Overlay that was playing when a new one started; held at PreviousOverlayTime during the cross-fade */
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> PreviousOverlaySequence;

	float OverlayTime = 0.f;
	float OverlayWeight = 0.f;
	float OverlayBlendIn = 0.1f;
	float OverlayBlendOut = 0.22f;
	float OverlayStartWeight = 0.f;
	float PreviousOverlayTime = 0.f;
	float CrossfadeAlpha = 1.f;
	float LowerBodyWeight = 1.f;

	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> StanceSequence;

	/** Stance being blended away from (null = the Anim Blueprint's own arms) */
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> PreviousStanceSequence;

	float StanceAlpha = 1.f;
	float StanceBlendTime = 0.25f;
	float StanceArmWeight = 1.f;
	float PreviousStanceArmWeight = 1.f;
	bool bStanceWholeBody = false;
	bool bPreviousStanceWholeBody = false;

	/** Overlay time at which the animation freezes (< 0 = plays to its end) */
	float OverlayStopTime = -1.f;
	float OverlayHoldRemaining = 0.f;
	float OverlayFadeDuration = 0.15f;
	float OverlayFadeElapsed = 0.f;

	/** > 0: after the hold the overlay plays backwards to its start at this rate instead of fading */
	float OverlayRewindRate = 0.f;
	bool bOverlayRewinding = false;
};
